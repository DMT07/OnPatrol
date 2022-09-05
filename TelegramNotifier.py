import os, time, datetime, json, re
import asyncio, threading

from aiohttp import ClientError
from Common import aioEvent_ts #a thread safe asyncio.Event class
from Common import SyncCall, TelegramFloodController, TermToken, create_sqlite3_table
from aiogram import Bot as TelegramBot

from aiogram.utils.exceptions import NetworkError, RetryAfter, RestartingTelegram, Throttled, TelegramAPIError #, BadRequest, ConflictError, Unauthorized, MigrateToChat
from aiofiles import os as aio_os
aio_isdir  = aio_os.wrap(os.path.isdir)
aio_isfile = aio_os.wrap(os.path.isfile)

import logging
logger = logging.getLogger('on_patrol_server')

def telegram_message(bot_token,
                     chat_id,
                     msg_time=datetime.datetime.now().timestamp(), 
                     message = '', 
                     image_filenames = [],
                     username = '',
                     fullname = '',
                     phone_number = '',
                     group_name = '',
                     exp_time = 0,
                     is_group = False,
                     retry_count = 0,
                     camera_name = ''):
    msg = {
            'TIME '           : msg_time,
            'MESSAGE'         : message, 
            'IMAGE_FILENAMES' : image_filenames,  
            'BOT_TOKEN'       : bot_token,
            'USER_NAME'       : username,
            'FULL_NAME'       : fullname,
            'PHONE_NUMBER'    : phone_number,
            'CHAT_ID'         : chat_id, 
            'GROUP_NAME'      : group_name,
            'EXP_TIME'        : exp_time,
            'IS_GROUP'        : is_group,
            'RETRY_COUNT'     : retry_count,
            'IPC_NAME'        : camera_name}
    return msg


class DataBaseManager():
    def __init__(self, db_conn):
        self._db_conn = db_conn
        self._lock = asyncio.Lock()

    async def _execute(self, stmt, args):
        async with self._lock:
            result = await SyncCall(self._db_conn.execute, None, stmt, args)
        return result
    
    async def get_all_users_patrol_active(self):
        stmt = 'SELECT * FROM users WHERE patrol_active = 1 AND camera_notifications_enabled = 1 AND user_active = 1 AND telegram_enabled = 1 AND chatid <> "" COLLATE NOCASE'
        args = ()
        return await self._execute(stmt, args)    

    async def add_telegram_sent_items(self, bot_token, chat_id, msg_id, exp_time):
        stmt = "INSERT INTO telegram_sent_items (bot_token, chat_id, msg_id, exp_time, deleted) VALUES (?, ?, ?, ?, ?)"
        args = (bot_token, str(chat_id), str(msg_id), int(exp_time), 0,)
        return await self._execute(stmt, args) 

    async def get_telegram_sent_items_expired(self):
        stmt = "SELECT * FROM telegram_sent_items WHERE exp_time <= (?) and deleted = 0"
        args = (int(time.time()), )
        return await self._execute(stmt, args)

    async def set_telegram_sent_item_deleted(self, guid):
        stmt = 'UPDATE telegram_sent_items SET deleted = 1 where guid = (?)'
        args = (guid,)
        await self._execute(stmt, args)

    async def clear_telegram_sent_items_deleted(self):
        stmt = 'DELETE FROM telegram_sent_items where deleted = 1'
        args = ()
        await self._execute(stmt, args)

    async def setup_tables(self):     
        #Create sent_items table
        columns = [['BOT_TOKEN'  , 'text'], 
                   ['CHAT_ID'    , 'text'], 
                   ['MSG_ID'     , 'text'], 
                   ['EXP_TIME'   , 'integer'],
                   ['DELETED'    , 'integer']]
        indexs  = ['EXP_TIME', 'DELETED']
        await SyncCall(create_sqlite3_table, None, self._db_conn, 'telegram_sent_items', columns, indexs)
        logger.debug('[TelegramNotifier] Tables set up')


async def DirectMessageScheduler(loop, incoming_queue, send_queue, dbm, config, exit_flag):
    while(True):
        try:
            item = await SyncCall(incoming_queue.get, None)
            if isinstance(item, TermToken):
                logger.debug('[TelegramNotifier] TERMINATION REQUEST RECEIVED, terminating task')
                await send_queue.put(TermToken())
                break
            logger.debug('[TelegramNotifier] DirectMessageScheduler new queue item received')
            await send_queue.put(item)    
            
        except Exception as ex:
            logger.error(f'[DirectMessageScheduler] {str(ex)}', exc_info=True)
        

async def CameraNotificationScheduler(loop, incoming_queue, send_queue, dbm, config, exit_flag):
    while(True):
        try:
            item = await SyncCall(incoming_queue.get, None)
            if isinstance(item, TermToken):
                logger.debug('[TelegramNotifier] CameraNotificationScheduler TERMINATION REQUEST RECEIVED, terminating task')
                await send_queue.put(TermToken())
                break
            #Check if camera is scheduled for notification
            matched_camera_clusters = match_camera_clusters(camera_clusters = config['CAMERA_CLUSTERS'],
                                                            event_type      = item['EVENT_TYPE'],
                                                            event_time      = item['EVENT_TIME'],
                                                            ipc_name        = item['IPC_NAME'],
                                                            channel_name    = item['CHANNEL_NAME'],
                                                            channel_number  = item['CHANNEL_NUMBER'])
            #Process telegram notifications
            to_send =  process_group_notifications( item, matched_camera_clusters, config)
            #to_send += await process_direct_notifications(item, matched_camera_clusters, config, dbm)        
            if to_send:
                logger.debug(f'[TelegramNotifier] {item["IPC_NAME"]}: Sending {len(to_send)} notifications')
                for notification in to_send:
                    await send_queue.put(notification)
            else:
                logger.debug(f'[TelegramNotifier] {item["IPC_NAME"]}: No notifications found to send')
        except Exception as ex:
            logger.error(f'[TelegramNotifier] {str(ex)}', exc_info=True)

async def TelegramSendWorkerDispatcher(loop, send_queue, dbm, config, flood_controller, exit_flag, queue_flushed):
    worker_limiter        = asyncio.Semaphore(30)  #Limit number of send workers (max telgram api calls 30/sec)   
    retry_worker_limiter  = asyncio.Semaphore(1000) #Limit number of queued retry items

    while True:
        notification = await send_queue.get()
        if isinstance(notification, TermToken):
            logger.debug('[TelegramSendWorkerDispatcher] TERMINATION REQUEST RECEIVED, queue flushed, terminating task')
            queue_flushed.set()
            break
 
        await worker_limiter.acquire()
        loop.create_task(TelegramSendWorker(loop                 = loop,
                                            notification         = notification,
                                            send_queue           = send_queue,
                                            flood_controller      = flood_controller,
                                            dbm                  = dbm,
                                            ImagePath            = config['IMAGES_SAVE_PATH'],
                                            exit_flag            = exit_flag,
                                            worker_limiter       = worker_limiter,
                                            retry_worker_limiter = retry_worker_limiter),
                         name = 'TelegramSendWorker'
                         )

async def TelegramSendWorker(loop, notification, send_queue, flood_controller, dbm, ImagePath, exit_flag, worker_limiter, retry_worker_limiter):
    try:
        bot = TelegramBot(token=notification['BOT_TOKEN'])

        num_files = len(notification['IMAGE_FILENAMES'])        
        if num_files == 0 and notification['MESSAGE']:
            try:
                await flood_controller.delay(token=notification['BOT_TOKEN'], chat_id=notification['CHAT_ID'], is_group=notification['IS_GROUP'])
                msg_sent = await bot.send_message(chat_id=notification['CHAT_ID'], parse_mode='HTML', disable_web_page_preview = False, text = notification['MESSAGE'])
                if int(notification['EXP_TIME']) > 0:
                    await dbm.add_telegram_sent_items(notification['BOT_TOKEN'], msg_sent.chat.id, msg_sent.message_id, int(notification['EXP_TIME'])+time.time() )
                logger.info(f' [TelegramNotifier] {notification["IPC_NAME"]}: Text message sent to {str(notification["PHONE_NUMBER"])} : {str(notification["USER_NAME"])} ({str(notification["FULL_NAME"])} {str(notification["GROUP_NAME"])})')
            except (RetryAfter, NetworkError, RestartingTelegram, ClientError, Throttled) as ex:
                #Retry Sending
                await handle_telegram_exception_retry(loop, notification, retry_worker_limiter, send_queue, str(ex), exit_flag)
            except TelegramAPIError as ex:
                #Retry if Gateway Timeout exception (GatewayTimeoutError not implemented yet)
                if str(ex).strip() == 'Gateway Timeout':
                    await handle_telegram_exception_retry(loop, notification, retry_worker_limiter, send_queue, str(ex), exit_flag)
                else:
                    logger.error(f'[TelegramNotifier] {notification["IPC_NAME"]}: Failed to send telegram notification. {str(ex)}')
                    pass
            except Exception as ex:
                #If there is some other telegram error, ignore this alert
                logger.error(f'[TelegramNotifier] {notification["IPC_NAME"]}: Failed to send telegram notification. {str(ex)}')
                pass
        elif num_files > 0:
            for num in range(0,num_files):
                if await aio_isfile(os.path.join(ImagePath, notification['IMAGE_FILENAMES'][num])):
                    try:
                        if os.path.splitext(notification['IMAGE_FILENAMES'][num])[1] == '.mp4':
                            await flood_controller.delay(token=notification['BOT_TOKEN'], chat_id=notification['CHAT_ID'], is_group=notification['IS_GROUP'])
                            msg_sent = await bot.send_video(chat_id=notification['CHAT_ID'], video=open(os.path.join(ImagePath, notification['IMAGE_FILENAMES'][num]), 'rb'), caption = notification['MESSAGE'])
                            logger.info(f' [TelegramNotifier] {notification["IPC_NAME"]}: Video sent to {str(notification["PHONE_NUMBER"])} : {str(notification["USER_NAME"])} ({str(notification["FULL_NAME"])} {str(notification["GROUP_NAME"])})')
                        else:
                            await flood_controller.delay(token=notification['BOT_TOKEN'], chat_id=notification['CHAT_ID'], is_group=notification['IS_GROUP'])
                            msg_sent = await bot.send_photo(chat_id=notification['CHAT_ID'], photo=open(os.path.join(ImagePath, notification['IMAGE_FILENAMES'][num]), 'rb'), caption = f'({num+1}/{num_files}) '+ notification['MESSAGE'])
                            logger.info(f' [TelegramNotifier] {notification["IPC_NAME"]}: Image sent to {str(notification["PHONE_NUMBER"])} : {str(notification["USER_NAME"])} ({str(notification["FULL_NAME"])} {str(notification["GROUP_NAME"])})')
                        if int(notification['EXP_TIME']) > 0:
                            await dbm.add_telegram_sent_items(notification['BOT_TOKEN'], msg_sent.chat.id, msg_sent.message_id, int(notification['EXP_TIME'])+time.time() )
                        notification['IMAGE_FILENAMES'][num] = ''
                    except (RetryAfter, NetworkError, RestartingTelegram, ClientError, Throttled) as ex:
                        #Retry Sending
                        await handle_telegram_exception_retry(loop, notification, retry_worker_limiter, send_queue, str(ex), exit_flag)
                    except TelegramAPIError as ex:
                        #Gateway Timeout exception is not implemented in aiogram yet, so manually test for it here
                        if str(ex).strip() == 'Gateway Timeout':
                            await handle_telegram_exception_retry(loop, notification, retry_worker_limiter, send_queue, str(ex), exit_flag)
                        else:
                            logger.error(f'[TelegramNotifier] {notification["IPC_NAME"]}: Failed to send telegram notification. {str(ex)}')
                            pass                        
                    except Exception as exp:
                        logger.error(f'[TelegramNotifier] {notification["IPC_NAME"]}: Failed to send telegram notification. {str(exp)}')
                        pass
    except Exception as exxx:
        logger.error(f'[TelegramNotifier] {notification["IPC_NAME"]}: {str(exxx)}')
    finally:
        if bot._session:
            await bot._session.close()
        worker_limiter.release()

async def handle_telegram_exception_retry(loop, notification, retry_worker_limiter, send_queue, ex_str, exit_flag):
    retry_limit = 5
    notification['RETRY_COUNT'] += 1
    
    if notification['RETRY_COUNT'] > retry_limit:
        logger.error(f'[TelegramNotifier] {notification["IPC_NAME"]}: Telegram send failed, retry limit exceeded. {ex_str}')
        return

    match = re.search('Retry in ([0-9]*) seconds', ex_str)
    if match is not None:
        delay = int(match[1]) 
    elif notification['RETRY_COUNT'] > 1:
        delay = 10
    else:
        delay = 5
    
    logger.info(f' [TelegramNotifier] {notification["IPC_NAME"]}: Telegram send failed, retry attempt {str(notification["RETRY_COUNT"])} in {str(delay)}s. {ex_str}')

    await retry_worker_limiter.acquire()
    loop.create_task(queue_after_delay(item         = notification,
                                       delay        = delay,
                                       queue        = send_queue,
                                       task_limiter = retry_worker_limiter,
                                       exit_flag    = exit_flag))

async def queue_after_delay(item, delay, queue, task_limiter, exit_flag):
    try:
        try:
            await asyncio.wait_for(exit_flag.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass 
        await queue.put(item)
    finally:
        task_limiter.release()
        
def process_group_notifications(item, matched_camera_clusters, config):
    '''
    This function will load alert-configs and check if the alert matches any
    criteria for any of the alert-configs. If an alert-conf criteria is 
    matched, it will build an alert and add to the bot telegram_sendqueue
    '''
    
    if len(matched_camera_clusters) < 1:
        return []
    
    to_send = []

    for conf in config['NOTIFICATIONS']:    
        if not conf['ENABLED'] or not conf['LIVE_VERIFICATION']['ACTIVE']:
            continue
        
        #Build item message
        message = build_notification_message(item, conf['INDICATE_EVENT_TYPE'])
        
        #Check if notification is in a camera cluster              
        if not any(x in matched_camera_clusters for x in conf['CAMERA_CLUSTERS']):
            continue
        
        to_send.append(telegram_message(bot_token = conf.get( 'BOT_TOKEN', '' ),
                                        chat_id = conf.get( 'BOT_CHAT_ID', '' ), 
                                        message = message, 
                                        image_filenames = item['IMAGE_FILENAMES'],
                                        group_name = conf.get( 'BOT_GROUP_NAME', '' ),
                                        exp_time = conf.get( 'MSG_EXPIRY_TIME', 0  ),
                                        is_group = True,
                                        camera_name=item['IPC_NAME']))

        logger.debug(f'[TelegramNotifier] {item["IPC_NAME"]}: Queuing notification: {conf["NOTIFICATION_NAME"]}')
        
    return to_send


async def process_direct_notifications(item, matched_camera_clusters, config, dbm):
    '''
    This function will check if there are any phone numbers or aliases in the 
    alert that matches the users list. If there are matches it will 
    create an alert message for each matching user found and add it to the 
    telegram bot's telegram_sendqueue.
    '''
    if len(matched_camera_clusters) < 1:
        return []
    
    to_send = []
        
    #Get list of users from the alert that are matched in the users list
    try:
        users = await dbm.get_all_users_patrol_active()
    except:
        users = []
    if len(users) == 0:
        return to_send
    
    #Build alert message
    Message = build_notification_message(item)
    
    #Add alert to telegram_sendqueue for each user
    
    for user in users:
        try:
            user_camera_clusters = json.loads(user['CAMERA_CLUSTERS'])
        except:
            continue
        
        #Check if user is in a camera cluster
        if not any(x in matched_camera_clusters for x in user_camera_clusters):
            continue
        
        to_send.append(telegram_message(bot_token = config.get('BOT_TOKEN', ''),
                                        chat_id = user.get('CHATID',''),
                                        message = Message, 
                                        image_filenames = item['IMAGE_FILENAMES'],
                                        username = user.get('USER_NAME',''),
                                        fullname = user.get('FULL_NAME',''),
                                        phone_number = user.get('NUMBER',''),
                                        exp_time = config['DIRECT_ALERT_EXPIRY_TIME'],
                                        is_group = False,
                                        camera_name = item['IPC_NAME']))
    
    return to_send


def build_notification_message(item, indicate_event_type=False):
    if indicate_event_type:
        message = f'{item["EVENT_TYPE"]}\n'
    else:
        message = ''
    
    message += f'{item["IPC_NAME"]}'
    # if item['CHANNEL_NAME'] not in ['', item['IPC_NAME']]:    
    #     message += f'{item["CHANNEL_NAME"]}'
    # elif item['IPC_NAME'] != '':
    #     message += f'{item["IPC_NAME"]}'
        
    message += f'\n{item["EVENT_TIME"].strftime("%Y-%m-%d %H:%M:%S")}'

    return message


def match_camera_clusters(camera_clusters, event_type, event_time, ipc_name, channel_name, channel_number):
    CameraClusterList = []
    for key in camera_clusters.keys():
        for cam in camera_clusters[key]:
            if cam['ENABLED']:
                if match_name(ipc_name.lower(), cam['IPC_NAMES']):
                    if match_name(channel_name.lower(), cam['CHANNEL_NAMES']):
                        if channel_number in cam['CHANNEL_NUMBERS'] or cam['CHANNEL_NUMBERS'] == []:
                            if any(x.lower() in cam['EVENT_TYPES'] for x in event_type) or cam['EVENT_TYPES'] == [] or 'Test Notification.' in event_type:
                                if cam['TIME_START'] > cam['TIME_STOP']:
                                    if event_time.time() < cam['TIME_STOP'] or event_time.time() > cam['TIME_START']:
                                        if cam[event_time.strftime("%A").upper()]:
                                            if key not in CameraClusterList:
                                                CameraClusterList.append(key)                            
                                elif cam['TIME_START'] < cam['TIME_STOP']:
                                    if event_time.time() > cam['TIME_START'] and event_time.time() < cam['TIME_STOP']:
                                        if cam[event_time.strftime("%A").upper()]:
                                            if key not in CameraClusterList:
                                                CameraClusterList.append(key)
                                else:
                                    if cam[event_time.strftime("%A").upper()]:
                                            if key not in CameraClusterList:
                                                CameraClusterList.append(key)
    return CameraClusterList        

def match_name(name, name_list):
    if  name_list == [] or '*' in name_list or name in name_list or \
        any(name.startswith(x[:-1]) for x in name_list if x.endswith('*')):
        return True
    else:
        return False

async def SentItemsCleanupWorker(dbm, flood_controller, exit_flag):
    while not exit_flag.is_set():
        try:
            items = await dbm.get_telegram_sent_items_expired()
            for item in items:
                if exit_flag.is_set():
                    break
                await flood_controller.delay(token=item['BOT_TOKEN'], chat_id=item['CHAT_ID'], is_group = True, api_only=True)
                bot = TelegramBot(token=item['BOT_TOKEN'])
                try:    
                    await bot.delete_message(chat_id=item['CHAT_ID'], message_id=item['MSG_ID'])
                except (RetryAfter, NetworkError, RestartingTelegram, ClientError, Throttled):
                    continue
                except TelegramAPIError as ex:
                    if str(ex).strip() == 'Gateway Timeout':
                        continue
                except:
                    pass
                finally:
                    if bot._session:
                        await bot._session.close()
                try:
                    await dbm.set_telegram_sent_item_deleted(item['GUID'])
                except:
                    pass
            try:
                await asyncio.wait_for(exit_flag.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
        except Exception as ex:
            print(ex)
            pass
        
        
async def TelegramNotifierMain(config, db_conn, camera_notification_queue, direct_message_queue, exit_flags):
    try:
        loop=asyncio.get_running_loop()
    except:
        loop=asyncio.new_event_loop()
    
    exit_flag = aioEvent_ts()
    exit_flags.append(exit_flag)
    queue_flushed = asyncio.Event()
    dbm = DataBaseManager(db_conn)
    await dbm.setup_tables()
    flood_controller = TelegramFloodController(token_burst_limit=29)
    send_queue = asyncio.Queue(1000)


    loop.create_task(SentItemsCleanupWorker(dbm              = dbm, 
                                            flood_controller = flood_controller,
                                            exit_flag        = exit_flag))
    
    loop.create_task(DirectMessageScheduler(loop            = loop, 
                                            incoming_queue  = direct_message_queue,
                                            send_queue      = send_queue,
                                            dbm             = dbm, 
                                            config          = config,
                                            exit_flag       = exit_flag))
    
    
    loop.create_task(CameraNotificationScheduler(loop      = loop, 
                                           incoming_queue  = camera_notification_queue,
                                           send_queue      = send_queue,
                                           dbm             = dbm, 
                                           config          = config,
                                           exit_flag       = exit_flag))
    
    loop.create_task(TelegramSendWorkerDispatcher(loop             = loop,
                                            send_queue       = send_queue,
                                            dbm              = dbm,
                                            config           = config,
                                            flood_controller = flood_controller,
                                            exit_flag        = exit_flag,
                                            queue_flushed    = queue_flushed))
    
    
    #Shutdown sequence: allow queues to flush through and finish up first
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.gather(*tasks)
  
    
class TelegramNotifier(threading.Thread):
    def __init__(self, config, db_conn, camera_notification_queue, direct_message_queue):    
        threading.Thread.__init__(self)
        self.name = 'TelegramNotifier'
        self.config = config
        self.db_conn = db_conn
        self.camera_notification_queue = camera_notification_queue
        self.direct_message_queue = direct_message_queue
        self.exit_flags = []

    def run(self):
        logger.debug('[TelegramNotifier] Started')

        asyncio.run(TelegramNotifierMain(config                    = self.config,
                                         db_conn                   = self.db_conn,
                                         camera_notification_queue = self.camera_notification_queue,
                                         direct_message_queue      = self.direct_message_queue,
                                         exit_flags                = self.exit_flags))
    
    def stop(self):
        for flag in self.exit_flags:
            flag.set()
        #self.camera_notification_queue.maxsize+=1
        self.camera_notification_queue.put(TermToken()) #Allow queues to flush through
        self.direct_message_queue.put(TermToken())
        self.join()
        logger.debug('[TelegramNotifier] Stopped')














