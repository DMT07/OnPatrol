import os
import asyncio, threading, aiohttp
from calendar import day_name
from Common import SyncCall, TermToken
from aiofiles import os as aio_os
aio_isdir  = aio_os.wrap(os.path.isdir)
aio_isfile = aio_os.wrap(os.path.isfile)

import logging
logger = logging.getLogger('on_patrol_server')
   
class DeepStackClient(threading.Thread):
    def __init__(self, IncomingQueue, OutgoingQueues, Config):    
        threading.Thread.__init__(self)
        self.name = 'DeepStackClient'
        self.config = Config
        self.incoming_queue = IncomingQueue
        self.outgoing_queues = OutgoingQueues
        self.exit_flags = []

    def run(self):
        asyncio.run(self.DeepStackClientMain())
    
    def stop(self):
        for flag in self.exit_flags:
            flag.set()
        self.incoming_queue.put(TermToken()) #Allow queues to flush through
        for queue in self.outgoing_queues.values():
            queue.put(TermToken())
        self.join()
        logger.debug('[DeepstackClient]  Stopped')

    async def DeepStackClientMain(self):
        logger.debug('[DeepstackClient]  Started')
        try: 
            self.loop=asyncio.get_running_loop()
        except:
            self.loop=asyncio.new_event_loop()
        while(True):
            try:
                item = await SyncCall(self.incoming_queue.get, None)
                if isinstance(item, TermToken):
                    logger.debug('[DeepStackClient]  TERMINATION REQUEST RECEIVED, terminating service')
                    break
                self.loop.create_task(self.IncomingHandler(item))   
            except Exception as ex:
                logger.error(f'[DeepStackClientMain]  {str(ex)}', exc_info=True)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*tasks)

    async def IncomingHandler(self, item):
        logger.debug(f'[DeepStackClient]  {str(item["IPC_NAME"])}: received {str(len(item["IMAGES"]))} images')
        try:
            CameraProfile = self.GetCameraProfile(item)
            if item['IMAGES']:
                if CameraProfile:
                    async with aiohttp.ClientSession() as session:
                        try:
                            results = await asyncio.gather(*[self.DeepStackQuery(session, CameraProfile['MIN_CONFIDENCE'], img['payload'], name=str(item['IPC_NAME'])) for img in item['IMAGES']])
                        except Exception as resultexp:
                            logger.error('[DeepStackClient]  ' + str(item['IPC_NAME']) + ': Failed to perform object detection, ' +str(resultexp) )
                        finally:
                            await session.close()
                    unique_objects = [obj.lower() for obj in set(sum(results, [])) if isinstance(obj, str)]
                    if unique_objects:
                        item['EVENT_TYPE'].extend(unique_objects) 
                    logger.info(' [DeepStackClient]  ' + str(item['IPC_NAME']) + ': RESULT (Conf >= ' + str(CameraProfile['MIN_CONFIDENCE']) + ') ' + str(unique_objects))                                                  
                else:
                    logger.debug('[DeepStackClient]  ' + str(item['IPC_NAME']) + ': Skipping detection, no profile rule matched')
            else:
                logger.debug('[DeepStackClient]  ' + str(item['IPC_NAME']) + ': Skipping detection, no images')
        except Exception as ex:
            logger.error('[DeepStackClient]  ' + str(item['IPC_NAME']) + ': Failed to perform object detection, ' +str(ex) )
        
        for queue in self.outgoing_queues.values():
            await SyncCall(queue.put, None, item)

    async def DeepStackQuery(self, session, min_confidence, image_data, detection_zones = [], name=''):
        data={'min_confidence': str(min_confidence),
              'image'         : image_data}
        if self.config['DEEPSTACK_API_KEY']:
            data['api_key'] = self.config['DEEPSTACK_API_KEY']
        labels = []
        
        try:
            async with session.post(self.config['DEEPSTACK_URL'], data=data, timeout=90) as resp:
                result = await resp.json()
                if resp.ok:
                    if result['success']:
                        if detection_zones:
                            # TODO: can add a check to make sure object is in detection zone
                            labels = [obj['label'] for obj in result['predictions']] # REPLACE TODO
                        else:
                            labels = [obj['label'] for obj in result['predictions']]
                    else:
                        labels.append('DeepStackFailed')
                        logger.debug(f'[DeepStackQuery]   {name}: {str(id(session))}: Detection failed: {result["error"]}')
                else:
                    labels.append('DeepStackFailed')
                    logger.debug(f'[DeepStackQuery]   {name}: {str(id(session))}: {resp.text}')
        except Exception as ex:
            labels.append('DeepStackFailed')
            logger.error(f'[DeepStackQuery]   {name}: {str(id(session))}: Failed: {str(ex)}')
        return labels

    def GetCameraProfile(self, item):
        # Check for individual camera name rules
        if item['IPC_NAME'].lower() in self.config['DEEPSTACK_CAMERA_NAME_INDEX'].keys():
            profile_keys = self.config['DEEPSTACK_CAMERA_NAME_INDEX'][item['IPC_NAME'].lower()]
            logger.debug(f'[DeepStackClient]  {str(item["IPC_NAME"])}: using profile {str(profile_keys)}')
            for key in profile_keys:
                profile = self.config['DEEPSTACK_CAMERA_PROFILES'][key]
                #Check channel names
                if profile['CHANNEL_NAMES']:
                    if item['CHANNEL_NAME'].lower() not in profile['CHANNEL_NAMES']:
                        continue
                #Check channel numbers
                if profile['CHANNEL_NUMBERS']:
                    if item['CHANNEL_NUMBER'].lower() not in profile['CHANNEL_NUMBERS']:
                        continue
                #Check weekday
                if not profile[day_name[item['EVENT_TIME'].weekday()].upper()]:
                    continue
                #Check time slot
                if profile['TIME_START'] > profile['TIME_STOP']:
                    if item['EVENT_TIME'].time() < profile['TIME_STOP'] or item['EVENT_TIME'].time() >= profile['TIME_START']:
                        return profile
                elif profile['TIME_START'] < profile['TIME_STOP']:
                    if item['EVENT_TIME'].time() < profile['TIME_STOP'] and item['EVENT_TIME'].time() >= profile['TIME_START']:
                        return profile
                else:
                    return profile

        # Check for rules that apply to all camera (wildcard *)
        #   Note: keys in DEEPSTACK_ALL_CAMERAS_INDEX are also the keys in 
        #   DEEPSTACK_CAMERA_PROFILES. The values in DEEPSTACK_ALL_CAMERAS_INDEX
        #   are a list of camera names to ignore.
        for key in self.config['DEEPSTACK_ALL_CAMERAS_INDEX'].keys():
            #Check if camera name is excluded from wildcard
            if item['IPC_NAME'].lower() in self.config['DEEPSTACK_ALL_CAMERAS_INDEX'][key]:
                continue
            
            profile = self.config['DEEPSTACK_CAMERA_PROFILES'][key]
            #Check channel names
            if profile['CHANNEL_NAMES']:
                if item['CHANNEL_NAME'].lower() not in profile['CHANNEL_NAMES']:
                    continue
            #Check channel numbers
            if profile['CHANNEL_NUMBERS']:
                if item['CHANNEL_NUMBER'].lower() not in profile['CHANNEL_NUMBERS']:
                    continue
            #Check weekday
            if not profile[day_name[item['EVENT_TIME'].weekday()].upper()]:
                continue
            #Check time slot
            if profile['TIME_START'] > profile['TIME_STOP']:
                if item['EVENT_TIME'].time() < profile['TIME_STOP'] or item['EVENT_TIME'].time() >= profile['TIME_START']:
                    logger.debug('[DeepStackClient]  ' + str(item['IPC_NAME']) + ': using profile ' + str(key))
                    return profile
            elif profile['TIME_START'] < profile['TIME_STOP']:
                if item['EVENT_TIME'].time() < profile['TIME_STOP'] and item['EVENT_TIME'].time() >= profile['TIME_START']:
                    logger.debug('[DeepStackClient]  ' + str(item['IPC_NAME']) + ': using profile ' + str(key))
                    return profile
            else:
                logger.debug('[DeepStackClient]  ' + str(item['IPC_NAME']) + ': using profile ' + str(key))
                return profile
            
        return None
        





