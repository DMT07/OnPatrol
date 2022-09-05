import json, time, queue
import threading, os
from pathlib import Path
from Common import make_valid_filename, create_mp4, TermToken, create_sqlite3_table

import logging
logger = logging.getLogger('on_patrol_server')

class DataBaseManager():
    def __init__(self, DBconn):
        self._DBconn = DBconn
    
    def add_camera_log(self, camera_id, event_type, event_time, ipc_name, ipc_sn, channel_name, channel_number):
        stmt = 'INSERT INTO camera_log (CAMERA_ID, EVENT_TYPE, EVENT_TIME, IPC_NAME, IPC_SN, CHANNEL_NAME, CHANNEL_NUMBER) VALUES (?,?,?,?,?,?,?)'
        args = (camera_id, event_type, event_time, ipc_name, ipc_sn, channel_name, channel_number,)
        return self._DBconn.execute(stmt, args)

    def add_image(self, filename, time, log_guid=''):
        if str(filename).strip() == '':
            return       
        stmt = 'INSERT INTO images (FILENAME, TIME, LOG_GUID) VALUES (?,?,?)'
        args = (str(filename), int(time), log_guid,)
        return self._DBconn.execute(stmt, args)

    def get_images_older_than(self, exp_time):
        stmt = 'SELECT * FROM images where time <= (?)'
        args = (exp_time,)
        return self._DBconn.execute(stmt,args)
    
    def delete_image(self, filename):
        if str(filename).strip() == '':
            return           
        stmt = "DELETE FROM images WHERE filename = (?)"
        args = (filename,)
        self._DBconn.execute(stmt, args) 

    def delete_image_guid(self, guid):         
        stmt = "DELETE FROM images WHERE guid = (?)"
        args = (guid,)
        self._DBconn.execute(stmt, args) 

    def setup_tables(self):  
        # create_sqlite3_table() automatically adds a GUID primary key column
        # create camera log table
        columns = [['CAMERA_ID'     , 'integer'],
                   ['EVENT_TYPE'    , 'text'],
                   ['EVENT_TIME'    , 'integer'],
                   ['IPC_NAME'      , 'text'],
                   ['IPC_SN'        , 'text'],
                   ['CHANNEL_NAME'  , 'text'],
                   ['CHANNEL_NUMBER', 'text']]
        indexs = ['CAMERA_ID', 'EVENT_TYPE', 'EVENT_TIME', 'IPC_NAME','IPC_SN' ,'CHANNEL_NUMBER']
        create_sqlite3_table(self._DBconn, 'camera_log', columns, indexs)        
        # Create images table
        columns = [['FILENAME', 'text'], 
                   ['TIME'    , 'integer'], 
                   ['LOG_GUID', 'integer']]
        indexs  = ['FILENAME' , 'TIME', 'LOG_GUID']
        create_sqlite3_table(self._DBconn, 'images', columns, indexs)
        logger.debug('[NotificationRecr] Tables set up')

class NotificationRecorder():

    def __init__(self, IncomingQueue, OutgoingQueues, DBconn, Config, WorkerCount=4):    
        self.IncomingQueue = IncomingQueue
        self.OutgoingQueues = OutgoingQueues #A dict {'queuename':queue_obj}
        self.DBconn = DBconn
        self.Config = Config
        self.TermEvent = threading.Event()
        self.DBm = DataBaseManager(DBconn)
        self.WorkerCount = WorkerCount
        self._threads = []
    
    def start(self):
        self.DBm.setup_tables()
        for i in range(self.WorkerCount):
            self._threads.append(threading.Thread(target = NotificationRecorderWorker, 
                                                  args   = (self.IncomingQueue,
                                                            self.OutgoingQueues, 
                                                            self.DBm, 
                                                            self.Config, 
                                                            self.TermEvent,
                                                            )
                                                  )
                                 )
        self._threads.append(threading.Thread(target = ImagesDiskCleanUpWorker, 
                                                  args   = (self.DBm, 
                                                            self.Config['IMAGES_SAVE_PATH'], 
                                                            self.Config['IMAGES_KEEP_TIME'],
                                                            self.TermEvent,
                                                            )
                                                  )
                                 )
        
        for thread in self._threads:
            thread.start()
        logger.debug(f'[NotificationRecr] Started with {str(self.WorkerCount)} workers')

    def stop(self):    
        logger.debug('[NotificationRecr] stopping, waiting for queue to flush...')
        self.TermEvent.set()
        for i in range(self.WorkerCount):
            self.IncomingQueue.put(TermToken())        
        for thread in self._threads:
            thread.join()
        logger.debug('[NotificationRecr] Stopped')

def NotificationRecorderWorker(IncomingQueue, OutgoingQueues, DBm, Config, TermEvent):
    while not TermEvent.is_set() or not IncomingQueue.empty(): 
        try:
            Item = IncomingQueue.get()
            if isinstance(Item, TermToken):
                break

            #Set image path for camera name:
            sub_path = make_valid_filename(Item['IPC_NAME'] + ' Ch' + str(Item['CHANNEL_NUMBER']))    
            full_path = os.path.join(Config['IMAGES_SAVE_PATH'], sub_path)
            if not os.path.isdir(full_path):
                try:
                    os.mkdir(full_path)
                except Exception as dr_ex:
                    logger.error(dr_ex, exc_info=True)
            
            #Process and save images/video to file
            Item['IMAGE_FILENAMES'] = []
            base_filename = make_valid_filename(Item["EVENT_TIME"].strftime("%Y-%m-%d_%H.%M.%S"))
            num_images = len(Item['IMAGES'])
            if num_images > 0:
                if num_images == 1:
                    #Save one image
                    try:
                        sub_path_file = os.path.join(sub_path, base_filename + Item['IMAGES'][0]['type'])
                        full_path_file = os.path.join(Config['IMAGES_SAVE_PATH'], sub_path_file)
                        c = 1
                        while(os.path.exists(full_path_file)):
                            sub_path_file = os.path.join(sub_path, base_filename + f' ({c})' + Item['IMAGES'][0]['type'])
                            full_path_file = os.path.join(Config['IMAGES_SAVE_PATH'], sub_path_file)
                            c+=1
                        Path(full_path_file).touch()
                        with open(full_path_file, 'wb') as out:
                                out.write(Item['IMAGES'][0]['payload'])
                                out.flush()
                    except Exception as ex:
                        logger.error(f'[NotificationRecr] {Item["IPC_NAME"]}: Could not save image "{str(Item["IMAGES"][0]["filename"])}" to disk, {str(ex)}')
                    else:
                        Item['IMAGE_FILENAMES'].append(sub_path_file)
                else:
                    try:
                        sub_path_file = os.path.join(sub_path, base_filename + '.mp4')
                        full_path_file = os.path.join(Config['IMAGES_SAVE_PATH'], sub_path_file)
                        c = 1
                        while(os.path.exists(full_path_file)):
                            sub_path_file = os.path.join(sub_path, base_filename + f' ({c})' + '.mp4')
                            full_path_file = os.path.join(Config['IMAGES_SAVE_PATH'], sub_path_file)
                            c+=1
                        Path(full_path_file).touch()
                        create_mp4(images        = [img['payload'] for img in Item['IMAGES']], 
                                   framerate     = 1.25, 
                                   out_file_path = full_path_file)
                    except Exception as ex:
                        logger.warning(f'[NotificationRecr] {Item["IPC_NAME"]}: Failed to create video, saving individual images instead. {str(ex)}')
                        #No video created, save images instead
                        i = 1
                        
                        for img in Item['IMAGES']:
                            try:
                                sub_path_file = os.path.join(sub_path, base_filename + f'_({str(i)}of{num_images})' + img['type'])
                                full_path_file = os.path.join(Config['IMAGES_SAVE_PATH'], sub_path_file)
                                while(os.path.exists(full_path_file)):
                                    sub_path_file = os.path.join(sub_path, base_filename + f'_({str(i)}of{num_images})' + f' ({c})' + img['type'])
                                    full_path_file = os.path.join(Config['IMAGES_SAVE_PATH'], sub_path_file)
                                    c+=1
                                Path(full_path_file).touch()
                                with open(full_path_file, 'wb') as out:
                                        out.write(img['payload'])
                                        out.flush()
                            except Exception as ex:
                                logger.error(f'[NotificationRecr] {Item["IPC_NAME"]}: Could not save image "{str(img["filename"])}" to disk, {str(ex)}')
                            else:
                                Item['IMAGE_FILENAMES'].append(sub_path_file)
                            i+=1                
                    else:
                        Item['IMAGE_FILENAMES'].append(sub_path_file)
            
            # Delete images binary data now that its saved to disk
            del Item['IMAGES']
            
            logger.debug(f'[NotificationRecr] {Item["IPC_NAME"]}: Notification recorded')
            #Add notification to log table
            log_guid = DBm.add_camera_log(camera_id      = Item['CAMERA_ID'],
                                          event_type     = json.dumps(Item['EVENT_TYPE']),
                                          event_time     = Item['EVENT_TIME'].timestamp(),
                                          ipc_name       = Item['IPC_NAME'],
                                          ipc_sn         = Item['IPC_SN'],
                                          channel_name   = Item['CHANNEL_NAME'],
                                          channel_number = Item['CHANNEL_NUMBER'])
        
            #add image to database images table
            for filename in Item['IMAGE_FILENAMES']:
                DBm.add_image(filename=filename, time=time.time(), log_guid=log_guid)    
             
            
            for q in OutgoingQueues.values():
                try:
                    #If the queue is full, timeout to allow other incoming to be recorded
                    q.put(Item, timeout = 3)
                except queue.Full:
                    pass
        except Exception as ex_all:
            logger.error(ex_all, exc_info=True)
            
def ImagesDiskCleanUpWorker(DBm, ImagePath, ImagesKeepTime, TermEvent):
    while not TermEvent.is_set():
        try:
            expire_time = time.time()-ImagesKeepTime
            items = DBm.get_images_older_than(expire_time)
            for item in items:
                if TermEvent.is_set():
                    break
                try:
                    full_path = os.path.join(ImagePath, item['FILENAME'])
                    if os.path.exists(full_path):
                        os.remove(full_path)
                except:
                    pass
                finally:
                    try:
                        DBm.delete_image_guid(item['GUID'])
                    except:
                        pass
        except Exception as ex:
            logger.error(ex, exc_info=True)
        TermEvent.wait(timeout=60)