import os, cv2, string, re, time, asyncio, functools, logging.handlers#, threading, sys
from numpy import frombuffer
from email.utils import parseaddr as ParseEmailAddress


# class SysRedirect(object):
#     def __init__(self):
#         self.terminal = sys.stdout                    # To continue writing to terminal
#         self.allowed={}                                 # A dictionary of file pointers for file logging
#         self.nullwriter=open(os.devnull, 'w')
    
#     def register(self,ident=None):                    # To start redirecting to filename
#         if not ident:  
#             ident = threading.currentThread().ident     # Get thread ident (thanks @michscoots)
#         self.allowed[ident] = self.terminal

#     def deregister(self,ident=None):
#         if not ident:  
#             ident = threading.currentThread().ident     # Get thread ident (thanks @michscoots)
#         if ident in self.allowed.keys():
#             del self.allowed
    
#     def get_registered(self):
#         return self.allowed.keys()
    
#     def write(self, message):
#         ident = threading.currentThread().ident     # Get Thread id
#         self.allowed.get(ident, self.nullwriter).write(message)
  
#     def flush(self):
#         #this flush method is needed for python 3 compatibility.
#         #this handles the flush command by doing nothing.
#         #you might want to specify some extra behavior here.
#         pass 
    
#     def __del__(self):
#         if not self.nullwriter.closed:
#             self.nullwriter.close()
            
def is_email_address(address):
    return bool(re.search(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', address))


class CustomQueueListener(logging.handlers.QueueListener):
    """
    Class modified to allow adding, removing updating handlers
    """    
    def __init__(self, queue, *handlers, respect_handler_level=False):
        """
        Initialise an instance with the specified queue and
        handlers.
        """
        self.queue = queue
        #Change handlers from tuple to list
        self.handlers = list(handlers)
        self._thread = None
        self.respect_handler_level = respect_handler_level        

    def addHandler(self, hdlr):
        """
        Add the specified handler to this logger.
        """
        if not (hdlr in self.handlers):
            self.handlers.append(hdlr)

    def removeHandler(self, hdlr):
        """
        Remove the specified handler from this logger.
        """
        if hdlr in self.handlers:
            hdlr.close()
            self.handlers.remove(hdlr)


class LocalQueueHandler(logging.handlers.QueueHandler):
    def emit(self, record: logging.LogRecord) -> None:
        # Removed the call to self.prepare(), handle task cancellation
        try:
            self.enqueue(record)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.handleError(record)


class TermToken(object): pass


class aioEvent_ts(asyncio.Event):
    #A thread safe asyncio.Event
    def set(self):
        self._loop.call_soon_threadsafe(super().set)

valid_filename_chars = frozenset("-_.() %s%s" % (string.ascii_letters, string.digits))
def make_valid_filename(filename):
    return ''.join(c for c in filename.strip().replace('@','_at_').replace(':','-') if c in valid_filename_chars).replace('..','.').rstrip('.')


class TelegramFloodController():
    def __init__(self, group_time_limit=60, group_burst_limit=20, chat_time_limit=1, chat_burst_limit=1, token_time_limit=1, token_burst_limit=30):
        self.group_time_limit  = group_time_limit
        self.group_burst_limit = group_burst_limit
        self.chat_time_limit   = chat_time_limit
        self.chat_burst_limit  = chat_burst_limit
        self.token_time_limit  = token_time_limit
        self.token_burst_limit = token_burst_limit
        self.history           = {}

    async def delay(self, token, chat_id='', is_group=False, api_only=False):
        if token not in self.history:
            self.history.update({token:{'token':[], 'chats':{}, 'groups':{}}})
        
        if not api_only:
            #Limit group message rate if applicable
            if is_group:
                if chat_id not in self.history[token]['groups']:
                    self.history[token]['groups'].update({chat_id:[]})
                await self._group_delay(token, chat_id)
    
            #Limit chat message rate
            if chat_id not in self.history[token]['chats']:
                self.history[token]['chats'].update({chat_id:[]})
            await self._chat_delay(token, chat_id)    
        
        #Limit token API calls
        await self._token_delay(token, chat_id)


    async def _group_delay(self, token, chat_id):
        now = time.time()
        sleep_time = self._filter(self.history[token]['groups'][chat_id], now, self.group_time_limit, self.group_burst_limit)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    async def _chat_delay(self, token, chat_id):
        now = time.time()
        sleep_time = self._filter(self.history[token]['chats'][chat_id], now, self.chat_time_limit, self.chat_burst_limit)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)        

    async def _token_delay(self, token, chat_id):
        now = time.time()
        sleep_time = self._filter(self.history[token]['token'], now, self.token_time_limit, self.token_burst_limit)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)    

    def _filter(self, buffer, now, time_limit, burst_limit):
        t_window = now - time_limit
        sleep_time = 0
        if buffer and t_window > buffer[-1]:
            buffer[:] = [now]
        else:
            buffer[:] = [t for t in buffer if t >= t_window]
            if len(buffer) >= burst_limit:
                idx = len(buffer) - burst_limit
                time_to_action = buffer[idx] + time_limit
                buffer.append(time_to_action)
                sleep_time = time_to_action - now
            else:
                buffer.append(now)           
        return sleep_time




def splitemails2list(str_in):
    try:
        return list(filter(('').__ne__, [ParseEmailAddress(val.strip().lower())[1] for val in str_in.split(',')] ))
    except:
        return []


def SynchronousProcedure(obj, method, *args, **kwargs):
    if method is None:
        return obj(*args, **kwargs)
    else:
        return getattr(obj, method)(*args, **kwargs)
    

async def SyncCall(obj, method, *args, **kwargs):
    return await asyncio.get_event_loop().run_in_executor(None, 
                                                          functools.partial(SynchronousProcedure, 
                                                                            obj, 
                                                                            method, 
                                                                            *args, 
                                                                            **kwargs
                                                                            )
                                                          )                                                         
                                                          
            
def create_mp4(images, framerate, out_file_path, scaleF=0.4):
    '''
    Convert is list of images in bytearray to mp4 video and save it to file
    with a random filename. 

    Parameters
    ----------
    images : LIST
        List of bytearrays each representing an individual image.
    framerate : FLOAT
        1/frame_duration.
    scaleF : FLOAT, optional
        Scale original image. The default is 0.4.

    Returns
    -------
    STRING
        The filename of the saved video without the directory path.
    '''
    
    if len(images) < 2:
        raise RuntimeError('cannot create video, less than 2 images supplied')
    
    #Load frames
    frames = []
    for image in images:
        try:
            frame = cv2.imdecode( frombuffer(image, dtype='uint8'), cv2.IMREAD_COLOR )
            if frame is not None:
                frames.append(frame)
        except:
            pass
    
    if len(frames) < 2:
        raise RuntimeError('cannot create video, less than 2 frames successfully loaded')
    
    #Resize frames
    height = 432 #int(frames[0].shape[0]*scaleF)  
    width  = 768 #int(frames[0].shape[1]*scaleF)
    for i in range(len(frames)):
        frames[i] = cv2.resize(frames[i],(width,height))
   
    #Write video
    video = cv2.VideoWriter(out_file_path, cv2.VideoWriter_fourcc(*'mp4v'), framerate, (width, height))  
    for i in range(3):
        for frame in frames:
            video.write(frame)
    cv2.destroyAllWindows()
    video.release()   

    #Check that image is not empty
    if os.path.isfile(out_file_path):
        if os.stat(out_file_path).st_size < 10:
            try:
                os.remove(out_file_path)
            except:
                pass
            raise RuntimeError('Empty video rendered')
    else:
        raise RuntimeError('Video not written to disk')
    


def csv2list(str_in, lower=True):
    try:
        if lower:
            return list(filter(('').__ne__, [val.strip().lower() for val in str_in.split(',')] ))
        else:
            return list(filter(('').__ne__, [val.strip() for val in str_in.split(',')] ))
    except:
        return []


def time2seconds(time_str):
    '''
    Match a D:H:M string and convert it to seconds

    Returns
    -------
    ExpiryTimeSec : int


    '''
    try:
        regex = re.search('(([0-9]{,3}):){,1}(([0-5]{,1}[0-9]):([0-5][0-9]))',time_str)
    except:
        regex = None
    
    ExpiryTimeSec = 0
    
    if regex is not None:
        if len(regex.groups()) > 4:
            try:
                if regex[2] is not None:
                    ExpiryTimeSec += int(regex[2])*86400 #seconds per day
                if regex[4] is not None:
                    ExpiryTimeSec += int(regex[4])*3600 #seconds per hour
                if regex[5] is not None:
                    ExpiryTimeSec += int(regex[5])*60 #seconds per minute    
            except:
                pass
       
    return ExpiryTimeSec
   
            
    
def str2bool(x):
    #Return True if string is 'true' else False for all other
    if isinstance(x,str):
        return str(x or '').lower() in ('true', 'yes')
    else:
        return bool(x)

def xstr(s):
    '''
    This functions ensure that a String Type is ALWAYS returned.
    In some instanced, when the str() conversion cannot convert the variable
    to a string, it returns a NoneType. Or, for example, when the variable
    is a None Type the str() will return a None Type, were you actually would 
    like a blank string "". 
    '''    
    return str(s or '')


#Get file extension for for email media attachement type
def get_ctype_file_extension(ctype):
    return {'image/jpeg': '.jpg', 'image/png':'.png', 'image/jpg':'.jpg'}.get(ctype, f'.{ctype.split("/")[-1]}')

def create_sqlite3_table(DBconn, TableName, SetColumns, SetIndexes):
    '''
    TableName:     The table name to create
    SetColumns:    The list of columns to create ['col name', 'data type' [, False]]
    SetIndexs:     A list of indexs to create
    
    Automatically adds a GUID primary key column to every table
    
    RETURN:
    ActualColumns: The list of actual columns in the table 
    '''
    
    #Build table if not exist
    #TableStatement = f'CREATE TABLE IF NOT EXISTS {TableName} ( {SetColumns[0][0]}  {SetColumns[0][1]}'
    TableStatement = f'CREATE TABLE IF NOT EXISTS {TableName} ( GUID INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT'
    for col in SetColumns:
        if col[0].strip().lower()!='guid':
            TableStatement += f', {col[0]} {col[1]}'
    TableStatement += ')'
    DBconn.execute(TableStatement)
    
    #If table already exists, make sure all needed columns are there.
    #  Get names of existing columns in table:
    result = DBconn.execute(f'SELECT * from pragma_table_info("{TableName}")')
    ActualColumns = []
    for column in result:
        if len(column) > 1: ActualColumns.append(column[1])            
    
    #  Add any column that is not yet in the table
    init_var_types = {'text':'', 'integer':0, 'real':0.}
    for col in SetColumns:
        if col[0] not in ActualColumns and col[0].strip().lower()!='guid':
            stmt = f'ALTER TABLE {TableName} ADD COLUMN {col[0]} {col[1]}'
            DBconn.execute(stmt)   
            stmt = f'UPDATE {TableName} SET {col[0]} = {init_var_types[col[1]]}'
            DBconn.execute(stmt) 
           
    #Create Indexes for table
    for idx in SetIndexes:
        DBconn.execute(f'CREATE INDEX IF NOT EXISTS {idx}Index ON {TableName} ({idx} ASC)')
    
    if hasattr(DBconn,'commit'):
        DBconn.commit() 
    return

