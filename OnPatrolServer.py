## Requires Python >= 3.7

## The MIT License (MIT)
## ---------------------
##
## Copyright (C) 2022 Males Tomlinson
##
## ## Permission is hereby granted, free of charge, to any person obtaining
## a copy of this software and associated documentation files (the "Software"),
## to deal in the Software without restriction, including without limitation
## the rights to use, copy, modify, merge, publish, distribute, sublicense,
## and/or sell copies of the Software, and to permit persons to whom the
## Software is furnished to do so, subject to the following conditions:
##
## The above copyright notice and this permission notice shall be included
## in all copies or substantial portions of the Software.
##
## THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
## OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
## FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
## AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
## LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
## FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
## IN THE SOFTWARE.

'''
On Patrol Server
'''
__version__   = '1.3.6'
__build__     = '1'
__author__    = 'DM Tomlinson'
__copyright__ = 'Copyright (c) 2022 DM Tomlinson'
__license__   = '''The MIT License (MIT)'''


import shutup  # Supress aiogram bot.close() deprecation warning
shutup.please()

from packaging import version

from consolemenu import ConsoleMenu, Screen
from consolemenu.items import ExitItem
from consolemenu.prompt_utils import PromptUtils

import asyncio
import datetime
from dateutil.parser import parse as datetime_parser

import os, argparse, sys, psutil

from psutil import AccessDenied, TimeoutExpired, NoSuchProcess

import configparser
from aiohttp import ClientConnectorError
from aiogram.utils.exceptions import ChatNotFound, Unauthorized, NetworkError
import aiogram
if version.parse(aiogram.__version__).major > 2:
    raise('aiogram need to be v2.x') #aiogram v3.x implements bot context manager
from aiogram import Bot as TelegramBot 


import sqlite3
from sqlite3worker import Sqlite3Worker #Need to use own modified version

from TelegramNotifier import TelegramNotifier as TelegramNotifier_
from NotificationRecorder import NotificationRecorder as NotificationRecorder_


from Common import xstr, str2bool, csv2list, time2seconds, \
    splitemails2list, TelegramFloodController, \
    CustomQueueListener, is_email_address, LocalQueueHandler


from logging.handlers import TimedRotatingFileHandler
from logging import StreamHandler

import queue
import python_telegram_logger
import copy
import locale
locale.setlocale(locale.LC_ALL, '')

import logging


import json

from terminaltables import AsciiTable as SingleTable 

from console.utils import wait_key, cls

logger = logging.getLogger('on_patrol_server')

shutup.please()

SIXMONTHS = 60*60*24*182
PASSWORD_PATTERN = '^(?=.*?[A-Z])(?=.*?[a-z])(?=.*?[0-9])(?=.*?[#?!@$%^&*-]).{8,32}$'


#--- EMAIL_TEMPLATE_CONFIG
CAMERA_EMAIL_TEMPLATE = { 'EVENT_TYPE_RE'       : '',
                          'EVENT_TYPE_GROUP'    : 0 ,
                          'EVENT_DATETIME_RE'   : '',
                          'EVENT_DATE_GROUP'    : 0 ,
                          'EVENT_TIME_GROUP'    : 0 ,
                          'CAMERA_NAME_RE'      : '',
                          'CAMERA_NAME_GROUP'   : 0 ,
                          'SERIAL_NUMBER_RE'    : '',
                          'SERIAL_NUMBER_GROUP' : 0 ,
                          'CHANNEL_NAME_RE'     : '',
                          'CHANNEL_NAME_GROUP'  : 0 ,
                          'CHANNEL_NUMBER_RE'   : '',
                          'CHANNEL_NUMBER_GROUP': 0 ,
                          'TEST_MESSAGE_RE'     : '',
                          'TEST_MESSAGE_CAMERA_NAME_RE': '',
                          'TEST_MESSAGE_CAMERA_NAME_GROUP': ''}


#--- DEFAULT_CAMERACLUSTER_CONFIG

DEFAULT_CAMERACLUSTER_CONFIG = '''
;=====================================================================
;==== DO NOT REMOVE THE DEFAULT ENTRY - ADD NEW CAMERAS BELOW IT =====
;=====================================================================
;==  YOU CAN MODIFY VALUES IN THE DEFAULT ENTRY. THE VALUES IN THE  ==  
;==  DEFAULT ENTRY WILL BE USED WHERE PARAMETERS ARE NOT SPECIFIED  ==
;==  IN ANY OF THE OTHER ENTRIES BELOW IT.                          ==
;===================================================================== 

[DEFAULT]
; Comma separated list of IPC names | Leave blank for any IPT/C names 
IPC_NAMES        = 

; Leave blank for any channel names | Specify channel name contains 
CHANNEL_NAMES   = 

; Leave blank for all channel numbers | 0,1,2,3,4,...
CHANNEL_NUMBERS = 

; Comma separated list of event types | Leave blank for any event type
EVENT_TYPES     = Intrusion Detection, Person, DeepStackFailed

; Valid options: True | False
ENABLED         = True

; Specify daily start/stop times: hh:mm 
;   To disable: make start/stop times the same
;   Blank times will be treated as 00:00
TIME_START      = 21:00
TIME_STOP       = 06:00

; Valid options: True | False to specify days on which to notify
MONDAY          = True
TUESDAY         = True
WEDNESDAY       = True
THURSDAY        = True
FRIDAY          = True
SATURDAY        = True
SUNDAY          = True

;================================================ ====================
;==== ADD INDIVIDUAL CAMERAS GROUPS BELOW HERE =======================
;=============================================== =====================
'''



#--- DEFAULT_NOTIFICATION_CONFIG
DEFAULT_NOTIFICATION_CONFIG = ''';======================================== ==================================
;==== DO NOT REMOVE THE DEFAULT ENTRY - ADD NEW NOTIFICATIONS BELOW IT =====
;========================================================================= =
[DEFAULT]
NOTIFICATION_NAME = 

; Valid options: True | False
ENABLED           = False

; Comma separated list of camera_cluster config names to associate 
;  (no need to include .ini file extention)
CAMERA_CLUSTERS   = 

; Bot token
BOT_TOKEN         = 

; Channel chat_id
BOT_CHAT_ID       = 

; Group name
BOT_GROUP_NAME    = 

; Notification expiry time in DD:HH:MM
;  The time after which a message will be deleted from the Telegram chat
;  TO DISABLE: set to 00:00:00 or leave blank
MSG_EXPIRY_TIME   = 00:00:00

; Indicate the event type in the telegram message
;  Valid options: True | False
INDICATE_EVENT_TYPE = False
 
;===========================================================================
;==== ADD NOTIFICATIONS BELOW HERE =========================================
;===========================================================================
'''    

#--- EXAMPLE DATA SERVER PROFILE
EXAMPLE_DATA_SERVER_PROFILE = """
[DEFAULT]
; Section names should be a unique ID

; data_server should correspond to section name in ../data_servers.ini
data_server = 

; Comma delimited list of camera names (leave empty for all cameras)
cameras = 

"""

DEFAULT_DEEPSTACK_CAMERA_PROFILE = '''
;=====================================================================
;==== DO NOT REMOVE THE DEFAULT ENTRY - ADD NEW CAMERAS BELOW IT =====
;=====================================================================
;==  YOU CAN MODIFY VALUES IN THE DEFAULT ENTRY. THE VALUES IN THE  ==  
;==  DEFAULT ENTRY WILL BE USED WHERE PARAMETERS ARE NOT SPECIFIED  ==
;==  IN ANY OF THE OTHER ENTRIES BELOW IT.                          ==
;===================================================================== 

[DEFAULT]
; Valid options: True | False
ENABLED         = True

; Comma separated list of IPCamera names 
;   Use * or leave blank to allow all camera names
;   Add ! in front of a name to exclude it when * wildcard is used

IPC_NAMES       = 

; Leave blank for any channel names | Specify channel name contains 
CHANNEL_NAMES   = 

; Leave blank for all channel numbers | 0,1,2,3,4,...
CHANNEL_NUMBERS = 

; Specify the minimum confidence to accept for opject identification
MIN_CONFIDENCE  = 0.45

; Specify daily start/stop times to do detection: hh:mm 
;   For always on: make start/stop times the same
;   Blank times will be treated as 00:00
TIME_START      = 20:00
TIME_STOP       = 06:00

; Valid options: True | False to specify days on which to do detection
MONDAY          = True
TUESDAY         = True
WEDNESDAY       = True
THURSDAY        = True
FRIDAY          = True
SATURDAY        = True
SUNDAY          = True

;=====================================================================
;==== ADD INDIVIDUAL CAMERAS BELOW HERE ==============================
;==== !!! ENSURE NO DUPLICATE SECTION HEADINGS !!! ===================
;=====================================================================

[EXAMPLE_ALL_CAMERAS]
ENABLED         = True
IPC_NAMES       =
MIN_CONFIDENCE  = 0.45
TIME_START      = 20:00
TIME_STOP       = 06:00
'''

#--- DATA_SERVER_CONFIG_TEMPLATE
DATA_SERVER_CONFIG_TEMPLATE = {'ENABLED'              : False,
                                 'SERVER_NAME'          : '',
                                 'ADDRESS'              : '',
                                 'PORT'                 : 6280,
                                 'USERNAME'             : '',
                                 'PASSWORD'             : ''}



#--- NOTIFICATION_CONFIG_TEMPLATE
NOTIFICATION_CONFIG_TEMPLATE = {'NOTIFICATION_NAME'     : '',
                                'ENABLED'               : False,
                                'CAMERA_CLUSTERS'       : [],                               
                                'BOT_TOKEN'             : '',
                                'BOT_CHAT_ID'           : '',
                                'BOT_GROUP_NAME'        : '',
                                'MSG_EXPIRY_TIME'       : 0,
                                'INDICATE_EVENT_TYPE'   : False,
                                'LIVE_VERIFICATION'     : {'ACTIVE':False,
                                                           'REASON':'',
                                                           'BOT_USERNAME':'', 
                                                           'GROUP_NAME':''
                                                           }
                                }

#--- CAMERA_CONFIG_TEMPLATE
CAMERA_CONFIG_TEMPLATE = {'CAMERA_ENABLED'                : True,
                          'CAMERA_NAME'                   : '',
                          'CAMERA_DESCRIPTION'            : '',
                          'CAMERA_TECH_NOTES'             : '',
                          'CAMERA_SITE_NOTES'             : '',
                          'CAMERA_LATITUDE'               : '',
                          'CAMERA_LONGITUDE'              : '',
                          'CAMERA_MANUFACTURER'           : '',
                          'CAMERA_MODEL_SERIES'           : '',
                          'CAMERA_ADDRESS'                : '',
                          'CAMERA_PORT'                   : '',
                          'CAMERA_USERNAME'               : '',
                          'CAMERA_PASSWORD'               : '',
                          'CAMERA_CHANNEL_NUMBER'         : '',
                          'REPLY_TO_LOCAL_IP'             : False,
                          'ENABLE_EMAIL_NOTIFICATIONS'    : False,
                          'CAMERA_EMAIL_ADDRESS'          : '',
                          'CAMERA_EMAIL_TEMPLATE'         : '',
                          'ENABLE_WEBHOOK_NOTIFICATIONS'  : False,
                          'ENABLE_HTTP_API_NOTIFICATIONS' : False,
                          'ENABLE_FTP_NOTIFICATIONS'      : False,
                          'FTP_IMAGES_KEEP_TIME'          : '00:08:00'}


#--- UNREGISTERED_CAMERA_EMAIL_SENDERS_TEMPLATE
UNREGISTERED_CAMERA_EMAIL_SENDERS_TEMPLATE = {'EMAIL_ADDRESS':  '',
                                              'EMAIL_TEMPLATE': ''}


#--- CAMERA_GROUP_CONFIG_TEMPLATE
CAMERA_GROUP_CONFIG_TEMPLATE = {'IPC_NAMES'           : [],
                                'CHANNEL_NAMES'       : [],
                                'CHANNEL_NUMBERS'     : [],
                                'EVENT_TYPES'         : ['Intrusion Detection'],
                                'ENABLED'             : True,
                                'TIME_START'          : '21:00',
                                'TIME_STOP'           : '06:00',
                                'MONDAY'              : True,
                                'TUESDAY'             : True,
                                'WEDNESDAY'           : True,
                                'THURSDAY'            : True,
                                'FRIDAY'              : True,
                                'SATURDAY'            : True,
                                'SUNDAY'              : True
                            }

#--- DATA_SERVER_PROFILE_TEMPLATE
DATA_SERVER_PROFILE_TEMPLATE = {'DATA_SERVER' : '',
                                'CAMERAS': []}

#--- DEEP_STACK_CAMERA_CONFIG_TEMPLATE
DEEPSTACK_CAMERA_PROFILE_TEMPLATE = {'IPC_NAMES'           : [],
                                     'CHANNEL_NAMES'       : [],
                                     'CHANNEL_NUMBERS'     : [],
                                     'MIN_CONFIDENCE'      : 0.45,
                                     'ENABLED'             : True,
                                     'TIME_START'          : '21:00',
                                     'TIME_STOP'           : '06:00',
                                     'MONDAY'              : True,
                                     'TUESDAY'             : True,
                                     'WEDNESDAY'           : True,
                                     'THURSDAY'            : True,
                                     'FRIDAY'              : True,
                                     'SATURDAY'            : True,
                                     'SUNDAY'              : True
                                     }


#--- CONFIG                             
CONFIG =    {'BOT_TOKEN':'',
             'BOT_USERNAME':',',
             'ADMIN_GROUP_CHAT_ID':',',
             'TERMS_OF_USE':',',
             'DISABLE_WEB_PAGE_PREVIEW':',',
             'SMTP_ENABLED':True,
             #'SMTP_ALLOW_UNREGISTERD_CAMERAS': False,
             'SMTP_ONLY_ALLOW_SENT_FROM':',',
             'SMTP_PORT_NUMBER':',',
             'HOST_NAME':',',
             'HTTP_ENABLED':True,
             'HTTP_PORT_NUMBER':',',
             'IMAGES_KEEP_TIME': '01:00:00',
             'MIN_LAT':',',
             'MAX_LAT':',',
             'MIN_LONG':',',
             'MAX_LONG':',',
             'LICENSE_ACCEPTED':',',
             'NOTIFICATIONS':[],
             'CAMERA_CLUSTERS':{},
             'EXE_PATH':'',
             'DATA_PATH':'',
             'CONFIG_PATH':'',
             'CAMERA_CLUSTER_PATH':'',
             'IMAGES_SAVE_PATH':'',
             'LOG_NOTIFIER_TOKEN' : '',
             'LOG_NOTIFIER_CHAT_IDS': [],
             'LOG_NOTIFIER_SENDER_NAME' : '',
             'DIRECT_ALERT_EXPIRY_TIME':60*60*6,
             'SERVER_LONG_NAME':'',
             'SERVER_SHORT_NAME':'',
             'DEBUG': False,
             'RPC_ENABLED':  True,
             'RPC_HOSTNAME': '0.0.0.0',
             'RPC_PORT':     81,
             'RPC_SSL_ENABLED':  False,
             'RPC_CERT_PATH': ''
             }  

#https://telegram.me/botname?start=123456789



def kill_pid_lock(lockfile):
    '''
    This function checks if a lock file with a PID exists and terminate the
    process corresponding to that PID if it is running. If it is unable to
    terminate the PID, close this instance.
    '''
    #check if lock file exists
    if os.path.isfile(lockfile):
        #Is PID in lock file still running
        with open(lockfile, 'r') as f:
            lock = f.read()
        try:
            lock = json.loads(lock)
        except:
            lock = None
        
        if not isinstance(lock, dict):
            lock = None
            
        if lock is not None:
            if psutil.pid_exists(lock['pid']):
                if psutil.Process(lock['pid']).name() == lock['name']:
                    try:
                        p = psutil.Process(lock['pid'])
                        p.terminate()
                    except NoSuchProcess:
                        pass
                    except AccessDenied:
                        msg = '\nAccess Denied to terminate process. Check user priviliges. (press enter to continue)'
                        PromptUtils(Screen()).enter_to_continue(message=msg)
                        # sg.Popup('\nAccess Denied to terminate process. Check user priviliges',
                        #          keep_on_top=True)
                        exit(0)
                    except TimeoutExpired:
                        try:
                            p.kill()
                        except AccessDenied:
                            msg = '\nAccess Denied to terminate process. Check user priviliges. (press enter to continue)'
                            # PromptUtils(Screen()).enter_to_continue(message=msg)
                            # sg.Popup('\nAccess Denied to terminate process. Check user priviliges',
                            #          keep_on_top=True)
                            exit(0)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    try:
                        os.remove(lockfile)
                    except:
                        pass
    return


def check_pid_lock(lockfile):    
    '''
    This function checks if a lock file with a PID exists. 
    If that PID is still running, terminate this program.
    '''
    #check if lock file exists
    if os.path.isfile(lockfile):
        #Is PID in lock file still running
        with open(lockfile, 'r') as f:
            lock = f.read()
        try:
            lock = json.loads(lock)
        except:
            lock = None
        
        if not isinstance(lock, dict):
            lock = None
            
        if lock is not None:
            if psutil.pid_exists(lock['pid']):
                if psutil.Process(lock['pid']).name() == lock['name']:
                    msg = 'Another instance is already running. \n  Use -f flag to kill running instance and a start new one.\n  Use -k flag to kill running instance.\n (press enter to close)'
                    PromptUtils(Screen()).enter_to_continue(message=msg)
                    #sg.popup('\nAnother instance is already running. \n  Use -f flag to kill running instance and a start new one.\n  Use -k flag to kill running instance.\n',icon='lock_black.ico')
                    sys.exit(0)
    
    this_pid = os.getpid()
    newlock = {'pid':this_pid, 'name':psutil.Process(this_pid).name()}
    try:
        with open(lockfile, 'w') as f:  
            f.write( json.dumps(newlock) )
    except:
        pass


    
    
def load_config():
    global CONFIG
    try:
        config = configparser.ConfigParser(allow_no_value=True)
        config.read(os.path.join(CONFIG['CONFIG_PATH'] , 'config.ini'))
        sections = config.sections()
    except Exception as ex:
        logger.critical(f'Error loading config.ini\n{str(ex)}')
        raise OSError(f'Error loading config.ini\n{str(ex)}')
        
    #Check if config sections exist and if not create it.
    #if not 'TELEGRAM_CONFIG'                in sections: config.add_section('TELEGRAM_CONFIG')
    if not 'SERVER_DETAILS'                 in sections: config.add_section('SERVER_DETAILS')
    if not 'SMTP_CONFIG'                    in sections: config.add_section('SMTP_CONFIG')    
    if not 'HTTP_CONFIG'                    in sections: config.add_section('HTTP_CONFIG')  
    if not 'RECORDER_CONFIG'                in sections: config.add_section('RECORDER_CONFIG')
    if not 'TELEGRAM_LOG_NOTIFIER'          in sections: config.add_section('TELEGRAM_LOG_NOTIFIER')
    if not 'DEEPSTACK_CONFIG'               in sections: config.add_section('DEEPSTACK_CONFIG')
    
    
    if not config.has_option('SERVER_DETAILS', 'SERVER_LONG_NAME'):
        config.set('SERVER_DETAILS', 'SERVER_LONG_NAME', '')
    if not config.has_option('SERVER_DETAILS', 'SERVER_SHORT_NAME'):
        config.set('SERVER_DETAILS', 'SERVER_SHORT_NAME', '')    

    #Create and load SMTP server default values if not exists in file
    if not config.has_option('SMTP_CONFIG','SMTP_ENABLED'):
        config.set('SMTP_CONFIG','SMTP_ENABLED','True')
    if not config.has_option('SMTP_CONFIG','SMTP_ONLY_ALLOW_SENT_FROM'):
        config.set('SMTP_CONFIG','SMTP_ONLY_ALLOW_SENT_FROM','')
    # if not config.has_option('SMTP_CONFIG','SMTP_ALLOW_UNREGISTERD_CAMERAS'):
    #     config.set('SMTP_CONFIG','SMTP_ALLOW_UNREGISTERD_CAMERAS', False)   
    if not config.has_option('SMTP_CONFIG','SMTP_PORT_NUMBER'):
        config.set('SMTP_CONFIG','SMTP_PORT_NUMBER','25')
    if not config.has_option('SMTP_CONFIG','HOST_NAME'):
        config.set('SMTP_CONFIG','HOST_NAME','localhost')
    
    #Create and load HTTP server default values if not exists in file
    if not config.has_option('HTTP_CONFIG','HTTP_ENABLED'):
        config.set('HTTP_CONFIG','HTTP_ENABLED', 'True')     
    if not config.has_option('HTTP_CONFIG','HTTP_PORT_NUMBER'):
        config.set('HTTP_CONFIG','HTTP_PORT_NUMBER','80') 
        
    #Create and load Recorder config
    if not config.has_option('RECORDER_CONFIG','IMAGES_SAVE_PATH'):
        config.set('RECORDER_CONFIG','IMAGES_SAVE_PATH', './data/images')    
    if not config.has_option('RECORDER_CONFIG','IMAGES_KEEP_TIME'):
        config.set('RECORDER_CONFIG','IMAGES_KEEP_TIME', '01:00:00')        

    #Create and load Deepstack settings
    if not config.has_option('DEEPSTACK_CONFIG', 'DEEPSTACK_ENABLED'):
        config.set('DEEPSTACK_CONFIG', 'DEEPSTACK_ENABLED', 'False')
    if not config.has_option('DEEPSTACK_CONFIG', 'DEEPSTACK_SERVER'):
        config.set('DEEPSTACK_CONFIG', 'DEEPSTACK_SERVER', '')
    if not config.has_option('DEEPSTACK_CONFIG', 'DEEPSTACK_PORT'):
        config.set('DEEPSTACK_CONFIG', 'DEEPSTACK_PORT', '82')
    if not config.has_option('DEEPSTACK_CONFIG', 'DEEPSTACK_API_PATH'):
        config.set('DEEPSTACK_CONFIG', 'DEEPSTACK_API_PATH', '/v1/vision/detection')        
    if not config.has_option('DEEPSTACK_CONFIG', 'DEEPSTACK_API_KEY'):
        config.set('DEEPSTACK_CONFIG', 'DEEPSTACK_API_KEY', '')
    
    #Create and load Telegram log notifier settings
    if not config.has_option('TELEGRAM_LOG_NOTIFIER', 'ENABLED'):
        config.set('TELEGRAM_LOG_NOTIFIER', 'ENABLED', 'True')
    if not config.has_option('TELEGRAM_LOG_NOTIFIER', 'TOKEN'):
        config.set('TELEGRAM_LOG_NOTIFIER', 'TOKEN', '')
    if not config.has_option('TELEGRAM_LOG_NOTIFIER', 'CHAT_IDS'):
        config.set('TELEGRAM_LOG_NOTIFIER', 'CHAT_IDS', '')
    if not config.has_option('TELEGRAM_LOG_NOTIFIER', 'SENDER_NAME'):
        config.set('TELEGRAM_LOG_NOTIFIER', 'SENDER_NAME', 'OnPatrolServer')  

    with open(os.path.join(CONFIG['CONFIG_PATH'] , 'config.ini'), 'w') as configfile:
        config.write(configfile)

    
    #Load server details
    ServerDetails = config['SERVER_DETAILS']
    CONFIG['SERVER_SHORT_NAME'] = ServerDetails.get('SERVER_SHORT_NAME', '')
    CONFIG['SERVER_LONG_NAME'] = ServerDetails.get('SERVER_LONG_NAME', '')

    #Load SMTP Server config section
    SMTPConfig = config['SMTP_CONFIG']
    CONFIG['SMTP_ENABLED']                   =     str2bool(SMTPConfig.get('SMTP_ENABLED', True))
    CONFIG['SMTP_ONLY_ALLOW_SENT_FROM']      =     SMTPConfig.get('SMTP_ONLY_ALLOW_SENT_FROM', 'localbot@localhost.local')
    # CONFIG['SMTP_ALLOW_UNREGISTERD_CAMERAS'] =     str2bool(SMTPConfig.get('SMTP_ALLOW_UNREGISTERD_CAMERAS', False))
    CONFIG['SMTP_PORT_NUMBER']               = int(SMTPConfig.get('SMTP_PORT_NUMBER'       , '25') or 25)
    CONFIG['HOST_NAME']                      =     SMTPConfig.get('HOST_NAME'              , '127.0.0.1')

    #Load HTTP Server config section
    HTTPConfig = config['HTTP_CONFIG']
    CONFIG['HTTP_ENABLED'] = str2bool(HTTPConfig.get('HTTP_ENABLED',True))
    CONFIG['HTTP_PORT_NUMBER'] = int(HTTPConfig.get('HTTP_PORT_NUMBER','80') or 80)
    
    #Load recorder config section
    RecorderConfig = config['RECORDER_CONFIG']
    CONFIG['IMAGES_SAVE_PATH']      =     RecorderConfig.get('IMAGES_SAVE_PATH', './data/images')       
    #   Make sure a minimum of 5 minutes is kept to allow notifications to send images
    keeptime = time2seconds(RecorderConfig.get('IMAGES_KEEP_TIME', '01:00:00'))
    if keeptime < 300:
        keeptime = 300
        logger.warning('Loading config.ini: minimum IMAGES_KEEP_TIME set to 00:00:05')
    CONFIG['IMAGES_KEEP_TIME']      =     keeptime
    
    #Validate image path after loading it from config
    if CONFIG['IMAGES_SAVE_PATH'].strip() == '':
        CONFIG['IMAGES_SAVE_PATH'] = './data/images'
    if CONFIG['IMAGES_SAVE_PATH'].strip().startswith('./'):
        CONFIG['IMAGES_SAVE_PATH'] = os.path.join(CONFIG['EXE_PATH'], CONFIG['IMAGES_SAVE_PATH'][2:])    

    #Load DeepStack details
    deepstack_details = config['DEEPSTACK_CONFIG']
    CONFIG['DEEPSTACK_ENABLED']           = str2bool(deepstack_details.get('DEEPSTACK_ENABLED',))
    CONFIG['DEEPSTACK_SERVER']            = deepstack_details.get('DEEPSTACK_SERVER',)
    CONFIG['DEEPSTACK_PORT']              = int(deepstack_details.get('DEEPSTACK_PORT', '82') or 82)
    CONFIG['DEEPSTACK_API_PATH']          = deepstack_details.get('DEEPSTACK_API_PATH',)
    CONFIG['DEEPSTACK_API_KEY']           = deepstack_details.get('DEEPSTACK_API_KEY',)
    CONFIG['DEEPSTACK_URL']               = 'http://' + CONFIG['DEEPSTACK_SERVER'].strip('/') + ':' + str(CONFIG['DEEPSTACK_PORT']) + '/' + CONFIG['DEEPSTACK_API_PATH'].strip('/')
    
    #Load Telegram Log Notifier settings
    LogNotifierConfig = config['TELEGRAM_LOG_NOTIFIER']
    CONFIG['LOG_NOTIFIER_ENABLED'] = str2bool(LogNotifierConfig.get('ENABLED', 'False'))
    CONFIG['LOG_NOTIFIER_TOKEN'] = LogNotifierConfig.get('TOKEN', '')
    CONFIG['LOG_NOTIFIER_CHAT_IDS'] = csv2list(LogNotifierConfig.get('CHAT_IDS',''))
    CONFIG['LOG_NOTIFIER_SENDER_NAME'] = LogNotifierConfig.get('SENDER_NAME','OnPatrolServer')

    CONFIG['VERSION'] = __version__
    CONFIG['SUPPORTED_CLIENT_VERSION'] = '1.0.1'
    CONFIG['COPYRIGHT'] = __copyright__
    
    #Load module specific config
    reload_config()




                  

# def load_camera_config():
#     global CONFIG
#     logger.info(f'Loading camera configs from {CONFIG["CONFIG_PATH"]}')
    
#     config_path = os.path.join(CONFIG['CONFIG_PATH'] , 'cameras.ini')
#     data_path   = os.path.join(CONFIG['DATA_PATH']   , 'camera_data.dat')
    
#     #Load cameras.ini config file 
#     config = configparser.ConfigParser(allow_no_value=True)
#     try:
#         config.read(config_path)
#     except Exception as ex:
#         logger.warning(f'Error reading camera.ini from {config_path}\n{str(ex)}')

    
#     #Load stored usernames and passwords for identifying camera responses
#     if os.path.isfile(data_path):
#         try:
#             with open(data_path, 'rb') as f:
#                 data = pickle.load(f)
#             if not isinstance(data, dict):
#                 data = {}
#         except:
#             data  = {}
#     else:
#         data = {}
    
#     if not config.has_option('DEFAULT','CAMERA_NAME'):
#         config.set('DEFAULT','; ======================== ============================================')
#         config.set('DEFAULT','; ==== DO NOT REMOVE THE DEFAULT ENTRY - ADD NEW CAMERAS BELOW IT =====')
#         config.set('DEFAULT','; ================================ ====================================')
#         config.set('DEFAULT','; ==  YOU CAN MODIFY VALUES IN THE DEFAULT ENTRY. THE VALUES IN THE  ==')
#         config.set('DEFAULT','; ==  DEFAULT ENTRY WILL BE USED WHERE PARAMETERS ARE NOT SPECIFIED  ==')
#         config.set('DEFAULT','; ==  IN ANY OF THE OTHER ENTRIES BELOW IT.                          ==')
#         config.set('DEFAULT','; ===                                                               ===')
#         config.set('DEFAULT','; ==  !! ATTENTION: THE SECTION NAMES SHOULD BE USED AS A GUID       ==')
#         config.set('DEFAULT','; ==                THAT SHOULD NOT BE REUSED FOR OTHER CAMERAS.     ==')
#         config.set('DEFAULT','; ===================================================================== \n\n')
#         config.set('DEFAULT','CAMERA_NAME','')

#     if not config.has_option('DEFAULT','CAMERA_ENABLED'):
#         config.set('DEFAULT','CAMERA_ENABLED','True')

        
#     if not config.has_option('DEFAULT','CAMERA_DESCRIPTION'):
#         config.set('DEFAULT','CAMERA_DESCRIPTION','')


#     if not config.has_option('DEFAULT','CAMERA_TECH_NOTES'):
#         config.set('DEFAULT','CAMERA_TECH_NOTES','')

        
#     if not config.has_option('DEFAULT','CAMERA_SITE_NOTES'):
#         config.set('DEFAULT','CAMERA_SITE_NOTES','')
       

#     if not config.has_option('DEFAULT','CAMERA_LATITUDE'):
#         config.set('DEFAULT','CAMERA_LATITUDE','0')

        
#     if not config.has_option('DEFAULT','CAMERA_LONGITUDE'):
#         config.set('DEFAULT','CAMERA_LONGITUDE','0')
        
# #-----
#     if not config.has_option('DEFAULT','CAMERA_MANUFACTURER'):
#         config.set('DEFAULT','\n\n; Camera model and series')
#         config.set('DEFAULT','CAMERA_MANUFACTURER','')


#     if not config.has_option('DEFAULT','CAMERA_MODEL_SERIES'):
#         config.set('DEFAULT','CAMERA_MODEL_SERIES','')

# #-----
#     if not config.has_option('DEFAULT','CAMERA_ADDRESS'):
#         config.set('DEFAULT','\n\n; Access to camera')
#         config.set('DEFAULT','CAMERA_ADDRESS','')  


#     if not config.has_option('DEFAULT','CAMERA_PORT'):
#         config.set('DEFAULT','CAMERA_PORT','') 

        
#     if not config.has_option('DEFAULT','CAMERA_USERNAME'):
#         config.set('DEFAULT','CAMERA_USERNAME','') 


#     if not config.has_option('DEFAULT','CAMERA_PASSWORD'):
#         config.set('DEFAULT','CAMERA_PASSWORD','') 

#     if not config.has_option('DEFAULT','CAMERA_CHANNEL_NUMBER'):
#         config.set('DEFAULT','CAMERA_CHANNEL_NUMBER','1') 

# #----
#     if not config.has_option('DEFAULT','REPLY_TO_LOCAL_IP'):
#         config.set('DEFAULT','\n\n; Set camera to reply to host\'s local network ip,\n;  alternatively the specified public address will be used.')
#         config.set('DEFAULT','REPLY_TO_LOCAL_IP','False') 

# #----
#     if not config.has_option('DEFAULT','ENABLE_EMAIL_NOTIFICATIONS'):
#         config.set('DEFAULT','\n\n; Configure to accept email notifications from camera')
#         config.set('DEFAULT','ENABLE_EMAIL_NOTIFICATIONS','False') 


#     if not config.has_option('DEFAULT','CAMERA_EMAIL_ADDRESS'):
#         config.set('DEFAULT','CAMERA_EMAIL_ADDRESS','') 


#     if not config.has_option('DEFAULT','CAMERA_EMAIL_TEMPLATE'):
#         config.set('DEFAULT','CAMERA_EMAIL_TEMPLATE','') 

# #----
#     if not config.has_option('DEFAULT','ENABLE_WEBHOOK_NOTIFICATIONS'):
#         config.set('DEFAULT','\n\n; Configure camera to send HTTP notifications')
#         config.set('DEFAULT','ENABLE_WEBHOOK_NOTIFICATIONS','False') 
# #----
#     if not config.has_option('DEFAULT','ENABLE_HTTP_API_NOTIFICATIONS'):
#         config.set('DEFAULT','\n\n; Configure camera to send HTTP notifications')
#         config.set('DEFAULT','ENABLE_HTTP_API_NOTIFICATIONS','False') 

# #----
#     if not config.has_option('DEFAULT','ENABLE_FTP_NOTIFICATIONS'):
#         config.set('DEFAULT','\n\n; Configure camera to send FTP notifications')
#         config.set('DEFAULT','ENABLE_FTP_NOTIFICATIONS','False')

#     if not config.has_option('DEFAULT','FTP_IMAGES_KEEP_TIME'):
#         config.set('DEFAULT','\n\n; Configure camera to send FTP notifications')
#         config.set('DEFAULT',';  FTP_IMAGES_KEEP_TIME in DD:HH:MM,\n;  TO DISABLE: set to 00:00:00 or leave blank')
#         config.set('DEFAULT','FTP_IMAGES_KEEP_TIME','00:08:00')

#         config.set('DEFAULT','\n\n; ==== ================================================================')
#         config.set('DEFAULT','; ====  ADD INDIVIDUAL CAMERAS BELOW DEFAULT SECTION               ====')
#         config.set('DEFAULT','; ====                                                             == =')
#         config.set('DEFAULT','; ====  !! ATTENTION: THE SECTION NAMES SHOULD BE USED AS A GUID   ====')
#         config.set('DEFAULT','; ====                THAT SHOULD NOT BE REUSED FOR OTHER CAMERAS. ====')
#         config.set('DEFAULT','; ===== ===============================================================\n\n')

        
#     sections = config.sections()
#     cameras = {}
#     camera_usernames = {}
#     camera_emails = {}
    
#     new_data = {}
#     for section in sections:
#         new_camera = CAMERA_CONFIG_TEMPLATE.copy()
#         new_camera.update({'STATUS': 'UPDATING'})
#         for key in CAMERA_CONFIG_TEMPLATE:
#             if config.has_option(section,key):
#                 if isinstance(CAMERA_CONFIG_TEMPLATE[key],bool):
#                     new_camera[key] = str2bool(config[section][key])
#                 elif isinstance(CAMERA_CONFIG_TEMPLATE[key],int):
#                     new_camera[key] = int(config[section][key])        
#                 else:
#                     new_camera[key] = config[section][key]
#         new_camera['FTP_IMAGES_KEEP_TIME'] = time2seconds(new_camera['FTP_IMAGES_KEEP_TIME'])
#         try:
#             new_camera['CAMERA_PASSWORD'] = decrypt(new_camera['CAMERA_PASSWORD'])
#         except:
#             if new_camera['CAMERA_PASSWORD'].strip() != '':
#                 try:
#                     config[section]['CAMERA_PASSWORD'] = encrypt(new_camera['CAMERA_PASSWORD'])
#                 except:
#                     pass
        
#         if section in data.keys():
#             response_username = data[section].get('USERNAME', generate_code(size=32, chars=string.ascii_letters))
#             new_camera.update({'RESPONSE_PASSWORD': data[section].get('PASSWORD', generate_code(size=32, chars=string.ascii_letters))})
#         else:
#             while True:
#                 #Generate new username and ensure it is unique
#                 response_username = generate_code(size=32, chars=string.ascii_letters)
#                 not_found_in_data = True
#                 for key in data.keys():
#                         if response_username == data[key].get('USERNAME', None):
#                             not_found_in_data = False
#                 if response_username not in camera_usernames.keys() and not_found_in_data:
#                     break
#             new_camera.update({'RESPONSE_PASSWORD': generate_code(size=32, chars=string.ascii_letters)})
            
        
#         new_data.update({section:{'USERNAME': response_username,
#                                   'PASSWORD': new_camera['RESPONSE_PASSWORD']}})
        
#         cameras.update({section:new_camera})
#         camera_usernames.update({response_username:section})
#         if is_email_address(new_camera['CAMERA_EMAIL_ADDRESS']):
#             _camera_email_key = f'{new_camera["CAMERA_EMAIL_ADDRESS"]}:{new_camera["CAMERA_CHANNEL_NUMBER"]}'.lower()
#             if _camera_email_key not in camera_emails.keys():
#                 camera_emails.update({_camera_email_key:section})
#             else:
#                 logger.warning(f'Duplicate camera email addresses in cameras.ini. Ignoring email address: {new_camera["CAMERA_EMAIL_ADDRESS"]} with channel: {new_camera["CAMERA_CHANNEL_NUMBER"]} for camera id: {section}')
    
#     try:
#         with open(data_path, 'wb') as f:
#             pickle.dump(new_data, f)
#     except Exception as ex1:
#         logger.error('Error saving camera_data.dat ' + str(ex1))
    
#     with open(os.path.join(CONFIG['CONFIG_PATH'] , 'cameras.ini'), 'w') as configfile:
#         config.write(configfile)
    
#     CONFIG['CAMERAS'] = cameras
#     CONFIG['CAMERA_USERNAMES'] = camera_usernames
#     CONFIG['CAMERA_EMAILS'] = camera_emails
 

def reload_config(online_reload = False):
    #load_camera_config()
    load_NotificationConfig(online_reload)
    load_CameraClusterConfigs(online_reload)
    
    if CONFIG['SMTP_ENABLED']:
        load_email_templates(online_reload)
        load_unregistered_camera_email_senders(online_reload)
        
    if CONFIG['DEEPSTACK_ENABLED']:
        load_DeepStackCameraProfiles(online_reload)

    
def load_NotificationConfig(online_reload=False):
    global CONFIG
    UnverifiedNotificationConfigs = []
    path = os.path.join(CONFIG['CONFIG_PATH'] ,'notifications.ini')
    logger.info(f'Loading telegram group notifications from {path}')
    #Check if the notifications.ini files exists, if not, create it and include comments
    try:
        if not os.path.isfile(path):
            with open(path, 'w') as f: 
                f.write(DEFAULT_NOTIFICATION_CONFIG)     
    except Exception as ex:
        logger.critical(f'Error writing default telegram group notifications to {path}\n{str(ex)}')
        msg = f'Error writing default telegram group notifications to {path}\n{str(ex)}' + '\n\nPress enter to continue...'
        input(msg + '\n(Press enter to continue...)')
        if online_reload:
            return
        else:
            sys.exit(0)
        
    config = configparser.ConfigParser()
    try:
        config.read(path)
    except Exception as ex:
        msg = f'Error loading telegram group notifications from {path}\n{str(ex)}'
        logger.critical(msg)
        if online_reload:
            input(msg + '\n(Press enter to continue...)')
            return
        else:
            raise OSError(msg)
    sections = config.sections()
    
    for section in sections:
        new_notification = NOTIFICATION_CONFIG_TEMPLATE.copy()
        for key in NOTIFICATION_CONFIG_TEMPLATE:
            if config.has_option(section,key):
                if isinstance(NOTIFICATION_CONFIG_TEMPLATE[key],bool):
                    new_notification[key] = str2bool(config[section].get(key, 'False'))
                elif isinstance(NOTIFICATION_CONFIG_TEMPLATE[key],list):
                    new_notification[key] = csv2list(config[section].get(key, ''))                
                else:
                    new_notification[key] = config[section].get(key, '')#.lower()
        new_notification['MSG_EXPIRY_TIME'] = time2seconds(new_notification['MSG_EXPIRY_TIME'])
        UnverifiedNotificationConfigs.append(new_notification)
    try:
        loop = asyncio.get_running_loop()
    except:
        loop = asyncio.new_event_loop()
    CONFIG['NOTIFICATIONS'] = loop.run_until_complete(verify_chat_ids(UnverifiedNotificationConfigs))
    if len(UnverifiedNotificationConfigs) > 0:
        for conf in CONFIG['NOTIFICATIONS']:
            msg = ' -> '
            msg += f'[{conf["NOTIFICATION_NAME"]}]'
            if conf["ENABLED"]:
                msg += ' ENABLED'
            else:
                msg += ' DISABLED'
            if conf["LIVE_VERIFICATION"]["BOT_USERNAME"] != '':
                msg += f' Bot: {conf["LIVE_VERIFICATION"]["BOT_USERNAME"]}'
            if conf["LIVE_VERIFICATION"]["GROUP_NAME"] != '':
                msg += f',Group: {conf["LIVE_VERIFICATION"]["GROUP_NAME"]}'
            msg += f', {conf["LIVE_VERIFICATION"]["REASON"]}'
            
            if conf['ENABLED'] and not conf["LIVE_VERIFICATION"]["ACTIVE"]:
                logger.error(msg)
            elif not conf['ENABLED'] and not conf["LIVE_VERIFICATION"]["ACTIVE"]:
                logger.warning(msg)
            else:
                logger.info(msg)
    return

def load_DeepStackCameraProfiles(online_reload=False):
    global CONFIG
    
    config_path = os.path.join(CONFIG['CONFIG_PATH'],'deepstack_camera_profiles.ini')
    
    try:
        if not os.path.isfile(config_path):
            with open(config_path, 'w') as f: 
                f.write(DEFAULT_DEEPSTACK_CAMERA_PROFILE) 
    except Exception as ex:
        msg = 'Error creating deepstack_camera_profiles.ini\n'+ str(ex) + '\n\nPress enter to continue...'
        input(msg)
        if online_reload:
            return
        else:
            sys.exit(0)
    
    config = configparser.ConfigParser()

    try:
        config.read(config_path)
    except Exception as ex:
        msg = 'Error reading deepstack_camera_profiles.ini ' + str(ex) 
        logger.critical(msg)
        input(msg + '\n\nPress enter to continue...')
        if online_reload:
            return
        else:
            sys.exit(0)
    
    camera_profiles = {}       #Key->Section name:Value->dict
    camera_name_index = {}     #Key->Camera name:Value->list of sections
    all_cameras_index = {}     #Key->Section:Value->list of excluded cameras
    for section in config.sections():
        new_profile = DEEPSTACK_CAMERA_PROFILE_TEMPLATE.copy()
        for key in DEEPSTACK_CAMERA_PROFILE_TEMPLATE:
            if config.has_option(section,key):
                if isinstance(DEEPSTACK_CAMERA_PROFILE_TEMPLATE[key],bool):
                    new_profile[key] = str2bool(config[section].get(key, 'False'))
                elif isinstance(DEEPSTACK_CAMERA_PROFILE_TEMPLATE[key],list):
                    new_profile[key] = csv2list(config[section].get(key, ''))
                elif isinstance(DEEPSTACK_CAMERA_PROFILE_TEMPLATE[key],int):
                    new_profile[key] = int(config[section].get(key))  
                elif isinstance(DEEPSTACK_CAMERA_PROFILE_TEMPLATE[key],float):
                    new_profile[key] = float(config[section].get(key))     
                else:
                    new_profile[key] = str(config[section].get(key, '')).lower()

        #Parse TIME            
        try:
            new_profile['TIME_START'] = datetime.datetime.strptime(new_profile['TIME_START'],'%H:%M').time()
        except:
            new_profile['TIME_START'] = datetime.datetime.strptime('00:00','%H:%M').time()
        try:   
            new_profile['TIME_STOP'] = datetime.datetime.strptime(new_profile['TIME_STOP'],'%H:%M').time() 
        except:
            new_profile['TIME_STOP'] = datetime.datetime.strptime('00:00','%H:%M').time() 
        
        if new_profile['ENABLED']:
            # Only load enabled profiles
            camera_profiles.update({section.lower():new_profile})
            if new_profile['IPC_NAMES'] == []:
                if section.lower() not in all_cameras_index.keys():
                    all_cameras_index[section.lower()] = []
            else:
                for name in new_profile['IPC_NAMES']:
                    if name == '*':
                        #Add to all cameras
                        if section.lower() not in all_cameras_index.keys():
                            all_cameras_index[section.lower()] = []
                    elif name.startswith('!'):
                        #Only use if wildcard * is specified
                        if '*' in new_profile['IPC_NAMES']:
                            if section.lower() not in all_cameras_index.keys():
                                all_cameras_index[section.lower()] = [name[1:].lower()]
                            else:
                                if name[1:].lower() not in all_cameras_index[section.lower()]:
                                    all_cameras_index[section.lower()].append(name[1:].lower())
                    else:
                        # Add camera name to camera_name_index
                        if name.lower() in camera_name_index.keys():
                            if section.lower() not in camera_name_index[name.lower()]:
                                camera_name_index[name.lower()].append(section.lower())
                        else:
                            camera_name_index[name.lower()] = [section.lower()]
    
    CONFIG['DEEPSTACK_CAMERA_PROFILES']       = camera_profiles.copy()
    CONFIG['DEEPSTACK_CAMERA_NAME_INDEX']     = camera_name_index.copy()
    CONFIG['DEEPSTACK_ALL_CAMERAS_INDEX']     = all_cameras_index.copy()

def load_CameraClusterConfigs(online_reload=False):
    global CONFIG
    
    LoadCameraClusterConfigs = {}
    
    #Check if the example_camera_cluster_config.ini files exists, if not, create it and include comments
    #example_camera_cluster_config.ini will not be read
    try:
        if not os.path.isfile(os.path.join(CONFIG['CAMERA_CLUSTER_PATH'],'example_camera_cluster_config.ini')):
            with open(os.path.join(CONFIG['CAMERA_CLUSTER_PATH'],'example_camera_cluster_config.ini'), 'w') as f: 
                f.write(DEFAULT_CAMERACLUSTER_CONFIG) 
    except Exception as ex:
        msg = 'Error creating example_camera_cluster_config.ini\n'+ str(ex) + '\n\nPress enter to continue...'
        if online_reload:
            input(msg)
            return
        else:
            sys.exit(0)
    
    config = configparser.ConfigParser()
    
    for dirpath, dirnames, files in os.walk(CONFIG['CAMERA_CLUSTER_PATH']):
        files = [ file for file in files if file.endswith('.ini') ]
        try:
            files.remove('example_camera_cluster_config.ini')
        except ValueError:
            pass
        
        for file in files:
            config = configparser.ConfigParser()
            try:
                config.read(os.path.join(dirpath,file))
            except:
                continue
            
            LoadCameraClusterConfigs.update({os.path.splitext(file)[0].lower():[]}) 
            for section in config.sections():
                new_camera = CAMERA_GROUP_CONFIG_TEMPLATE.copy()
                for key in CAMERA_GROUP_CONFIG_TEMPLATE:
                    if config.has_option(section,key):
                        #PARSE BOOL
                        if isinstance(CAMERA_GROUP_CONFIG_TEMPLATE[key],bool):
                            new_camera[key] = str2bool(config[section].get(key, 'False'))
                        elif isinstance(CAMERA_GROUP_CONFIG_TEMPLATE[key],list):
                            new_camera[key] = csv2list(config[section].get(key, ''))
                        else:
                            new_camera[key] = str(config[section].get(key, '')).lower()
                #Convert to list of int
                #new_camera['CHANNEL_NUMBERS'] = ListStr2ListInt(new_camera['CHANNEL_NUMBERS'])
                
                #Parse TIME            
                try:
                    new_camera['TIME_START'] = datetime.datetime.strptime(new_camera['TIME_START'],'%H:%M').time()
                except:
                    new_camera['TIME_START'] = datetime.datetime.strptime('00:00','%H:%M').time()
                try:   
                    new_camera['TIME_STOP'] = datetime.datetime.strptime(new_camera['TIME_STOP'],'%H:%M').time() 
                except:
                    new_camera['TIME_STOP'] = datetime.datetme.strptime('00:00','%H:%M').time() 

                LoadCameraClusterConfigs[os.path.splitext(file)[0].lower()].append(new_camera)
    
    CONFIG['CAMERA_CLUSTERS'] = LoadCameraClusterConfigs.copy()



def load_email_templates(online_reload=False):
    global CONFIG
    logger.info(f'Loading email_templates.ini from {CONFIG["CONFIG_PATH"]}')
    template_path = os.path.join(CONFIG['CONFIG_PATH'] , 'email_templates.ini')

    #Load email_templates.ini config file 
    config = configparser.ConfigParser(allow_no_value=True)
    try:
        config.read(template_path)
    except Exception as ex:
        msg = f'Error reading email_templates.ini from {template_path}\n{str(ex)}'
        logger.error(msg)
        if online_reload:
            input(msg + '\n\nPress enter to continue...')
        else:
            sys.exit(0)

    #Load default template
    if not config.has_option('DEFAULT','EVENT_TYPE_RE'):
        config.set('DEFAULT','; ======================== ============================================')
        config.set('DEFAULT','; ==== DO NOT REMOVE THE DEFAULT ENTRY - ADD NEW TEMPLATES BELOW IT ===')
        config.set('DEFAULT','; ================================ ====================================')
        config.set('DEFAULT','; ==  YOU CAN MODIFY VALUES IN THE DEFAULT ENTRY. THE VALUES IN THE  ==')
        config.set('DEFAULT','; ==  DEFAULT ENTRY WILL BE USED WHERE PARAMETERS ARE NOT SPECIFIED  ==')
        config.set('DEFAULT','; ==  IN ANY OF THE OTHER SECTIONS BELOW IT.                         ==')
        config.set('DEFAULT','; ===                                                               ===')
        config.set('DEFAULT','; ==  THE SECTION NAMES WILL BE USED AS THE TEMPLATE NAMES           ==')
        config.set('DEFAULT','; ====                                                             ====')
        #config.set('DEFAULT','; ==  Escape literals \\, \\a, \\b, \\f, \\n, \\r, \\t, \\v with \\\          ==')
        config.set('DEFAULT','; ================================================================== == \n\n')
        config.set('DEFAULT','EVENT_TYPE_RE',r'EVENT TYPE:\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')    
    if not config.has_option('DEFAULT','EVENT_TYPE_GROUP'):
        config.set('DEFAULT', 'EVENT_TYPE_GROUP', '1')
        config.set('DEFAULT', ' ')

    if not config.has_option('DEFAULT','EVENT_DATETIME_RE'):
        config.set('DEFAULT', 'EVENT_DATETIME_RE', r'EVENT TIME:\s*([0-9]{4}\-[0-9]{2}\-[0-9]{2}),([0-9]{2}\:[0-9]{2}\:[0-9]{2})[\.\s]*[\r|\n]')
        config.set('DEFAULT', '  ')
    if not config.has_option('DEFAULT','EVENT_DATE_GROUP'):
        config.set('DEFAULT', 'EVENT_DATE_GROUP', '1')
        config.set('DEFAULT', '   ')
    if not config.has_option('DEFAULT','EVENT_TIME_GROUP'):
        config.set('DEFAULT', 'EVENT_TIME_GROUP', '2')
        config.set('DEFAULT', '    ')

    if not config.has_option('DEFAULT','CAMERA_NAME_RE'):
        config.set('DEFAULT', 'CAMERA_NAME_RE', r'([N|D]VR|IP[T|C]|IPDOME) NAME:\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')
        config.set('DEFAULT', '     ')
    if not config.has_option('DEFAULT','CAMERA_NAME_GROUP'):
        config.set('DEFAULT', 'CAMERA_NAME_GROUP', '2')
        config.set('DEFAULT', '      ')

    if not config.has_option('DEFAULT','SERIAL_NUMBER_RE'):
        config.set('DEFAULT', 'SERIAL_NUMBER_RE', r'([N|D]VR|IP[T|C]|IPDOME) S/N:\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')
        config.set('DEFAULT', '     ')
    if not config.has_option('DEFAULT','SERIAL_NUMBER_GROUP'):
        config.set('DEFAULT', 'SERIAL_NUMBER_GROUP', '2')
        config.set('DEFAULT', '      ')

    if not config.has_option('DEFAULT','CHANNEL_NAME_RE'):
        config.set('DEFAULT', 'CHANNEL_NAME_RE', r'CHANNEL NAME:\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')
        config.set('DEFAULT', '       ')
    if not config.has_option('DEFAULT','CHANNEL_NAME_GROUP'):
        config.set('DEFAULT', 'CHANNEL_NAME_GROUP', '1')
        config.set('DEFAULT', '        ')

    if not config.has_option('DEFAULT','CHANNEL_NUMBER_RE'):
        config.set('DEFAULT', 'CHANNEL_NUMBER_RE', r'CHANNEL NUMBER:\s*([0-9\-\_]*)\s*[\r|\n]')
        config.set('DEFAULT', '       ')
    if not config.has_option('DEFAULT','CHANNEL_NUMBER_GROUP'):
        config.set('DEFAULT', 'CHANNEL_NUMBER_GROUP', '1')
        config.set('DEFAULT', '        ')

    if not config.has_option('DEFAULT','TEST_MESSAGE_RE'):
        config.set('DEFAULT', 'TEST_MESSAGE_RE', r'^((This e-mail is used to test)|(this is a test mail from))')
        config.set('DEFAULT', '         ')

    if not config.has_option('DEFAULT','TEST_MESSAGE_CAMERA_NAME_RE'):
        config.set('DEFAULT', 'TEST_MESSAGE_CAMERA_NAME_RE', r'this is a test mail from\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')
        config.set('DEFAULT', '     ')
    if not config.has_option('DEFAULT','TEST_MESSAGE_CAMERA_NAME_GROUP'):
        config.set('DEFAULT', 'TEST_MESSAGE_CAMERA_NAME_GROUP', '1')
        config.set('DEFAULT', '      ')


    #Load hikvision_default template
    if not config.has_section('HIKVISION_DEFAULT'):
        config.add_section('HIKVISION_DEFAULT')
    
        config.set('HIKVISION_DEFAULT','EVENT_TYPE_RE', r'EVENT TYPE:\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')    
        config.set('HIKVISION_DEFAULT', 'EVENT_TYPE_GROUP', '1')
        config.set('HIKVISION_DEFAULT', ' ')

        config.set('HIKVISION_DEFAULT', 'EVENT_DATETIME_RE', r'EVENT TIME:\s*([0-9]{4}\-[0-9]{2}\-[0-9]{2}),([0-9]{2}\:[0-9]{2}\:[0-9]{2})[\.\s]*[\r|\n]')
        config.set('HIKVISION_DEFAULT', 'EVENT_DATE_GROUP', '1')
        config.set('HIKVISION_DEFAULT', 'EVENT_TIME_GROUP', '2')
        config.set('HIKVISION_DEFAULT', '    ')

        config.set('HIKVISION_DEFAULT', 'CAMERA_NAME_RE', r'([N|D]VR|IP[T|C]|IPDOME) NAME:\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')
        config.set('HIKVISION_DEFAULT', 'CAMERA_NAME_GROUP', '2')
        config.set('HIKVISION_DEFAULT', '      ')

        config.set('HIKVISION_DEFAULT', 'SERIAL_NUMBER_RE', r'([N|D]VR|IP[T|C]|IPDOME) S/N:\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')
        config.set('HIKVISION_DEFAULT', 'SERIAL_NUMBER_GROUP', '2')
        config.set('HIKVISION_DEFAULT', '         ')

        config.set('HIKVISION_DEFAULT', 'CHANNEL_NAME_RE', r'CHANNEL NAME:\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')
        config.set('HIKVISION_DEFAULT', 'CHANNEL_NAME_GROUP', '1')
        config.set('HIKVISION_DEFAULT', '           ')

        config.set('HIKVISION_DEFAULT', 'CHANNEL_NUMBER_RE', r'CHANNEL NUMBER:\s*([0-9\-\_]*)\s*[\r|\n]')
        config.set('HIKVISION_DEFAULT', 'CHANNEL_NUMBER_GROUP', '1')
        config.set('HIKVISION_DEFAULT', '             ')

        config.set('HIKVISION_DEFAULT', 'TEST_MESSAGE_RE', r'^((This e-mail is used to test)|(this is a test mail from))')
        config.set('HIKVISION_DEFAULT', '               ')

        config.set('HIKVISION_DEFAULT', 'TEST_MESSAGE_CAMERA_NAME_RE', r'this is a test mail from\s*([A-Za-z0-9_\-\s\.]*)\s*[\r|\n]')
        config.set('HIKVISION_DEFAULT', 'TEST_MESSAGE_CAMERA_NAME_GROUP', '1')
        config.set('HIKVISION_DEFAULT', '                ')


    
    sections = config.sections()
    email_templates = {}

    for section in sections:
        new_template = CAMERA_EMAIL_TEMPLATE.copy()
        for key in CAMERA_EMAIL_TEMPLATE:
            if config.has_option(section,key):
                if isinstance(CAMERA_EMAIL_TEMPLATE[key],bool):
                    new_template[key] = str2bool(config[section][key])
                elif isinstance(CAMERA_EMAIL_TEMPLATE[key],int):
                    new_template[key] = int(config[section][key] or 0)        
                else:
                    new_template[key] = str(config[section][key])
        email_templates.update({str(section).lower():new_template})            
                    
                    
    with open(template_path, 'w') as f:
        config.write(f)
    
    CONFIG['CAMERA_EMAIL_TEMPLATES'] = email_templates                    


def load_unregistered_camera_email_senders(online_reload=False):
    global CONFIG
    logger.info(f'Loading unregisterd_camera_email_senders.ini from {CONFIG["CONFIG_PATH"]}')
    file_path = os.path.join(CONFIG['CONFIG_PATH'] , 'unregistered_camera_email_senders.ini')

    #Load email_templates.ini config file 
    config = configparser.ConfigParser(allow_no_value=True)
    try:
        config.read(file_path)
    except Exception as ex:
        msg = f'Error reading unregistered_camera_email_senders.ini from {file_path}\n{str(ex)}'
        logger.error(msg)
        if online_reload:
            input(msg + '\n\nPress enter to continue...')
        else:
            sys.exit(0)

    #Load default template
    if not config.has_option('DEFAULT','EMAIL_ADDRESS'):
        config.set('DEFAULT','; ======================== ============================================')
        config.set('DEFAULT','; ==== DO NOT REMOVE THE DEFAULT ENTRY - ADD NEW TEMPLATES BELOW IT ===')
        config.set('DEFAULT','; ================================ ====================================')
        config.set('DEFAULT','; ==  YOU CAN MODIFY VALUES IN THE DEFAULT ENTRY. THE VALUES IN THE  ==')
        config.set('DEFAULT','; ==  DEFAULT ENTRY WILL BE USED WHERE PARAMETERS ARE NOT SPECIFIED  ==')
        config.set('DEFAULT','; ==  IN ANY OF THE OTHER SECTIONS BELOW IT.                         ==')
        config.set('DEFAULT','; ===                                                               ===')
        config.set('DEFAULT','; ==  THE SECTION NAMES SHOULD BE UNIQUE, BUT IS NOT USED            ==')
        config.set('DEFAULT','; ====                                                             ====')
        config.set('DEFAULT','; ================================================================== == \n\n')
        config.set('DEFAULT', '; Comma delimited list of email addresses')
        config.set('DEFAULT', 'EMAIL_ADDRESS', '')
        config.set('DEFAULT', ' ')
    if not config.has_option('DEFAULT','EMAIL_TEMPLATE'):
        config.set('DEFAULT', 'EMAIL_TEMPLATE', 'HIKVISION_DEFAULT')
        config.set('DEFAULT', '  ')
    
    sections = config.sections()
    email_addesses = {}

    for section in sections:
        if not config.has_option(section,'EMAIL_TEMPLATE'):
            continue
        template = config[section]['EMAIL_TEMPLATE'].lower()
        emails = csv2list(config[section]['EMAIL_ADDRESS'], lower=True)
        if template:
            for email in emails:
                if is_email_address(email):
                    if email in email_addesses.keys():
                        if email_addesses[email] != template:
                            logger.warning(f'{email} is defined multiple times with different templates in unregisterd_camera_email_senders.ini\n    Using the last entry found with template: {template}')
                    email_addesses.update({email:template})
    with open(file_path, 'w') as f:
        config.write(f)
    CONFIG['UNREGISTERED_EMAIL_TEMPLATES'] = email_addesses    

async def get_bot_username(token):
    try:
        bot = TelegramBot(token=token)
        me = await bot.get_me()
        username = me['username']
                
    except Exception as ex:
        print(ex)
        logger.error(f'Error retrieving chat bot username. {str(ex)}')
        username = ''
    finally:
        if bot._session:
            await bot._session.close()

    return username

async def verify_chat_ids(configs):
    checks = []
    flood_controller = TelegramFloodController(token_burst_limit=19)
    for config in configs:
        checks.append(verify_chat_id_worker(config, flood_controller))    
    results = await asyncio.gather(*checks)
    return results

async def verify_chat_id_worker(conf, flood_controller):
    verification = {'ACTIVE':False, 
                    'REASON':'',
                    'BOT_USERNAME':'', 
                    'GROUP_NAME':''
                    }
    bot = TelegramBot(token=conf['BOT_TOKEN'])
    try:
        await flood_controller.delay(token=conf['BOT_TOKEN'], 
                                     chat_id=conf['BOT_CHAT_ID'], 
                                     is_group = False, 
                                     api_only=True
                                     )
        me = await bot.get_me()
        try:
            await flood_controller.delay(token=conf['BOT_TOKEN'], 
                                         chat_id=conf['BOT_CHAT_ID'], 
                                         is_group = False, 
                                         api_only=True
                                         )
            chat = await bot.get_chat(chat_id=conf['BOT_CHAT_ID'])
        except ChatNotFound:
            verification['ACTIVE'] = False
            verification['REASON'] = 'CHAT NOT FOUND'
            verification['BOT_USERNAME'] = me['username']
        else:
            verification['ACTIVE'] = True
            verification['REASON'] = 'ACTIVE'
            verification['BOT_USERNAME'] = me['username']
            verification['GROUP_NAME'] = chat['title']
    except Unauthorized:
        verification['ACTIVE'] = False
        verification['REASON'] = 'TOKEN UNAUTHORISED'
    except (ClientConnectorError, NetworkError) as ex:
        logger.critical('verify_chat_id_worker(): '+ str(ex))
        verification['ACTIVE'] = True
        verification['REASON'] = 'Connection error, loaded as ACTIVE'
        conf['LIVE_VERIFICATION'] = verification
    finally:
        if bot._session:
            await bot._session.close()

    conf['LIVE_VERIFICATION'] = verification
    return conf    

def get_status_message(config, log_level):
    # status_msg  = 'SERVICES:\n'
    # status_msg += '-----------------'
    status_msg = ''
    if config['SMTP_ENABLED']:
        status_msg +=     f'\n[RUNNING] SMTP Server: {config["HOST_NAME"]}:{config["SMTP_PORT_NUMBER"]}'
    
    if config['HTTP_ENABLED']:
        status_msg +=     f'\n[RUNNING] HTTP Server: {config["HOST_NAME"]}:{config["HTTP_PORT_NUMBER"]}'

    if config['DEEPSTACK_ENABLED']:
        status_msg += '\n[RUNNING] DeepStack Client'  
    
    status_msg += '\n[RUNNING] Camera Notification Recorder'
    status_msg += '\n[RUNNING] Telegram Camera-Event Notifier'        

    if config['LOG_NOTIFIER_ENABLED']:
        if config['LOG_NOTIFIER_TOKEN'] and config['LOG_NOTIFIER_CHAT_IDS']:
            status_msg += '\n[RUNNING] Telegram Log Notifier'
        else:
            status_msg += '\n[ ERROR ] Telegram Log Notifier: Invalid token or chat id'
    if log_level > logging.DEBUG:
        status_msg += '\n[LOGGING] Debug: Off'
    else:
        status_msg += '\n[LOGGING] Debug: On'
        
    return status_msg

def get_telegram_group_message():
    global CONFIG
    data_table = [['STATUS', 'NOTIFICATION NAME', 'BOT NAME', 'GROUP NAME']]
    for conf in CONFIG['NOTIFICATIONS']:
        if conf["ENABLED"]:
            data_table.append([conf["LIVE_VERIFICATION"]["REASON"],
                               conf["NOTIFICATION_NAME"],
                               conf["LIVE_VERIFICATION"]["BOT_USERNAME"],
                               conf["LIVE_VERIFICATION"]["GROUP_NAME"]])
    table_instance = SingleTable(data_table, 'Enabled Telegram Camera Notifications')
    return f'\n {CONFIG["SERVER_LONG_NAME"]}\n\n' + str(table_instance.table) + '\n(Press ESC to close)'


def show_telegram_groups_status():
    cls()
    print(get_telegram_group_message())
    try:
        wait_for_esc()
    except KeyboardInterrupt:
        pass


    
def remove_all_stderr_logging_handlers():
    for name in logging.root.manager.loggerDict:
        try:
            logging.getLogger(name).removeHandler(sys.stderr)
        except:
            pass

def toggle_loglevel(log_handlers, log_level):
    if log_level > logging.DEBUG:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    for handler in log_handlers:
        try:
            handler.setLevel(log_level)
        except:
            pass
    return log_level

def show_live_log(listener, stream_handler, log_level):
    cls()
    if log_level > logging.DEBUG:
        log_msg = 'off'
    else:
        log_msg = 'on'
    print(f'{CONFIG["SERVER_LONG_NAME"]}\nLIVE LOG OUTPUT [debug {log_msg}] - Press ESC to close\n')
    listener.addHandler(stream_handler)
    try:
        wait_for_esc()
    except KeyboardInterrupt:
        pass
    listener.removeHandler(stream_handler)

def wait_for_esc():
    while True:
        if wait_key() in ['\x1b', '\x03']:
            break

def send_test_notification(listener, stream_handler, log_level, OutgoingQueues, History={}):                    

    try:
        with open(os.path.join(CONFIG['EXE_PATH'],'deepstack_test_image.jpg'),'rb') as f:
            image = f.read()
        images = [{'type': '.jpg', 'payload': image}]
    except:
        images = []
    default =  {'EVENT_TYPE'    :['Intrusion Detection'],
                'EVENT_TIME'    :datetime.datetime.now(),
                'IPC_NAME'      :'Dummy Test Camera',
                'IPC_SN'        :'',
                'CHANNEL_NAME'  :'Dummy Channel', 
                'CHANNEL_NUMBER':'0', 
                'IMAGES'        :images,
                'CAMERA_ID'     :None,
                'CAMERA_NAME'   :'Dummy Test Camera'
                }
    
    for key in [x for x in default.keys() if x not in History.keys()]:
        History[key] = default[key]
    
    while True:  
        msg =  'SEND TEST NOTIFICATION:\n\n'
        msg += f'Camera Name    : {History["IPC_NAME"]}\n'
        msg += f'Channel Name   : {History["CHANNEL_NAME"]}\n'
        msg += f'Channel Number : {History["CHANNEL_NUMBER"]}\n'
        msg += f'Event Type     : {History["EVENT_TYPE"]}\n'
        msg += f'Event Time     : {History["EVENT_TIME"]}\n'
        msg += '\nSelection option:' 
        cls()
        selection =  PromptUtils(Screen()).prompt_for_numbered_choice(choices=['Send', 'Edit', 'Reload Config', 'Cancel'], 
                                                                      title=msg)
        
        #if PromptUtils(Screen()).prompt_for_yes_or_no(msg):
        if selection == 1:
            print('\nLeave blank to use the [existing] values:')
            IPC_NAME, valid                  = PromptUtils(Screen()).input(prompt = 'Camera Name: ', default=History['IPC_NAME'])
            if IPC_NAME:
                History['IPC_NAME'] = str(IPC_NAME)
            
            CHANNEL_NAME, valid = PromptUtils(Screen()).input(prompt = 'Channel Name: ', default=History['CHANNEL_NAME'])
            if CHANNEL_NAME:
                History['CHANNEL_NAME']   = str(CHANNEL_NAME)
            
            CHANNEL_NUMBER, valid = PromptUtils(Screen()).input(prompt = 'Channel Number: ', default=History['CHANNEL_NUMBER'])
            if CHANNEL_NUMBER:
                History['CHANNEL_NUMBER'] = str(CHANNEL_NUMBER)
            
            EVENT_TYPE, valid = PromptUtils(Screen()).input(prompt = 'Event Type: (comma separated list)', default=','.join(History['EVENT_TYPE']))
            if EVENT_TYPE:
                History['EVENT_TYPE']     = csv2list(EVENT_TYPE)
            while True:
                time_str, valid = PromptUtils(Screen()).input(prompt = 'Event Time (YYYY-MM-DD HH:MM:SS): ', default=History['EVENT_TIME'].strftime("%Y-%m-%d %H:%M:%S"))
                if time_str:    
                    try:
                        History['EVENT_TIME'] = datetime_parser(time_str)
                    except:
                        PromptUtils(Screen()).enter_to_continue('Invalid event time given, try again or enter blank to use the current value.')
                        continue
                break
        elif selection == 0:
            print('LIVE LOG OUTPUT [debug] - Press ESC to return\n')
            listener.addHandler(stream_handler)
            for q in OutgoingQueues.values():
                q.put(copy.deepcopy(History))
            try:
                wait_for_esc()
            except KeyboardInterrupt:
                pass
            listener.removeHandler(stream_handler) 
        elif selection == 2:
            cls()
            print('reloading config...')
            reload_config(online_reload=True)
        elif selection == 3:
             break
    History['IMAGES'] = []

    
###############################################################################
#   MAIN                                                                      #
###############################################################################
def main():
    try:
        global CONFIG
        print('STARTING ON PATROL SERVER V' + str(__version__) + ' (PID:' + xstr(os.getpid()) + ')\nplease wait...')
    
        #Set path variables
        if getattr(sys, 'frozen', False):
            CONFIG['EXE_PATH'] = os.path.dirname(sys.executable)
        elif __file__:
            CONFIG['EXE_PATH'] = os.path.dirname(__file__)  
            
        CONFIG['DATA_PATH'] = os.path.join(CONFIG['EXE_PATH'],'data')
        CONFIG['CONFIG_PATH'] = os.path.join(CONFIG['DATA_PATH'],'config')
        CONFIG['LOG_PATH'] = os.path.join(CONFIG['DATA_PATH'],'log')
        CONFIG['CAMERA_CLUSTER_PATH'] = os.path.join(CONFIG['CONFIG_PATH'],'camera_clusters')
        
        LOCKFILE = os.path.join(CONFIG['EXE_PATH'] , str(os.path.splitext(__file__)[0]) + '.lock')
        DBFILE   = os.path.join(CONFIG['DATA_PATH'], 'data.sqlite') 
        
        #Create all sub-directories if not exists
        if not os.path.exists(CONFIG['DATA_PATH']):
            os.makedirs(CONFIG['DATA_PATH'])
        if not os.path.exists(CONFIG['CONFIG_PATH'] ):
            os.makedirs(CONFIG['CONFIG_PATH'] ) 
        if not os.path.exists(CONFIG['LOG_PATH'] ):
            os.makedirs(CONFIG['LOG_PATH'] )     
        if not os.path.exists(CONFIG['CAMERA_CLUSTER_PATH']):
            os.makedirs(CONFIG['CAMERA_CLUSTER_PATH'])    
        
        
        #Set up commandline parse arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('-k','--kill'    , action='store_true',  help='Terminate the running instance and remove the lock file')
        parser.add_argument('-f','--force'   , action='store_true',  help='Kill running instance in lock file and start new')    
        parser.add_argument('-d','--debug'   , action='store_true',  help='Output debug')
        
        #Parse the commandline arguments
        args, unknown_args = parser.parse_known_args()
    
        #Process the --kill [-k] and --force [-f] commandline flags
        if args.kill:
            kill_pid_lock(LOCKFILE)
            return
        elif args.force:
            kill_pid_lock(LOCKFILE)
        
        check_pid_lock(LOCKFILE)
        
        if args.debug:
            log_level = logging.DEBUG
        else:
            log_level = logging.INFO
            remove_all_stderr_logging_handlers()

        #Set up a logging file_handler
        log_filename = 'events.log'
        log_file_path = os.path.join(CONFIG['LOG_PATH'], log_filename)
        all_log_handlers = []
        log_queue = queue.SimpleQueue()
        f_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        file_handler = TimedRotatingFileHandler(filename      = log_file_path,
                                                when          = 'midnight',
                                                interval      = 1,
                                                backupCount   = 90)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(f_format)
        all_log_handlers.append(file_handler)
        
        stream_format  = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s\r')
        stream_handler = StreamHandler(sys.stdout)
        stream_handler.setLevel(log_level)
        stream_handler.setFormatter(stream_format)
        all_log_handlers.append(stream_handler)
        
        #Set up logging listener
        listener = CustomQueueListener(log_queue,
                                       *[file_handler],
                                        respect_handler_level=True)
        listener.start()
        
        #Remove all other root logger handlers
        root_logger = logging.getLogger()
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
        root_logger.setLevel(log_level)
        all_log_handlers.append(root_logger)
        
        #Configure logger instance
        queue_handler = LocalQueueHandler(log_queue)
        queue_handler.setLevel(log_level)
        all_log_handlers.append(queue_handler)
        
        logger.setLevel(log_level)
        logger.addHandler(queue_handler)
        all_log_handlers.append(logger)
        
        if not os.path.isfile(os.path.join(CONFIG['CONFIG_PATH'], 'config.ini')):
            new_config = True
        else:
            new_config = False
        
        load_config()
        
        #Check/Create image path
        if not os.path.exists(CONFIG['IMAGES_SAVE_PATH']):
            try:
                os.makedirs(CONFIG['IMAGES_SAVE_PATH'])
            except Exception as exp:
                logger.critical(f'Cannot create images folder at {CONFIG["IMAGES_SAVE_PATH"]}\n{str(exp)}')
                
        if new_config:
            logger.info(f'Default config.ini generated at {CONFIG["CONFIG_PATH"]}. Terminating application.')
            msg = '\nDefault config.ini file generated\n'+os.path.join(CONFIG['CONFIG_PATH'], 'config.ini')+'\n\nPlease edit config.ini and restart the program. \n\nPress enter to close...\n'
            PromptUtils(Screen()).enter_to_continue(message=msg)
            return        
        
        if CONFIG['LOG_NOTIFIER_ENABLED'] and CONFIG['LOG_NOTIFIER_TOKEN'] and CONFIG['LOG_NOTIFIER_CHAT_IDS']:
            telegram_handler = python_telegram_logger.Handler(token    = CONFIG['LOG_NOTIFIER_TOKEN'],
                                                              chat_ids = CONFIG['LOG_NOTIFIER_CHAT_IDS'])
            telegram_handler.setLevel(logging.ERROR)
            FMT = f'<b>%(levelname)s</b>\n<i>{CONFIG["LOG_NOTIFIER_SENDER_NAME"]}</i>\n<pre>%(message)s</pre> %(exc)s'
            telegram_formatter = python_telegram_logger.HTMLFormatter(FMT)
            telegram_handler.setFormatter(telegram_formatter)
            listener.addHandler(telegram_handler)
        
        DeepStackInQueue        = queue.SimpleQueue()#maxsize=1000)
        RecorderInQueue         = queue.SimpleQueue()#maxsize=1000)
        NotifierInQueue         = queue.SimpleQueue()#maxsize=1000)
        DirectMessageInQueue    = queue.SimpleQueue()#maxsize=1000)
        threads                 = []
        DBconn                  = Sqlite3Worker(DBFILE, row_factory=sqlite3.Row) #Starts a thread, need to .close() again
    
                   
        try:
            if CONFIG['SMTP_ENABLED']:
                from EmailServer import SMTPServer as SMTPServer_
                if CONFIG['DEEPSTACK_ENABLED']:
                    # Pass output to DeepStack
                    SMTPServer_OutgoingQueues = {'DeepStackInQueue':DeepStackInQueue}
                else:
                    # Pass output directly to Notification Recorder
                    SMTPServer_OutgoingQueues = {'RecorderInQueue': RecorderInQueue}
                SMTPServer_Thread = SMTPServer_(Hostname          = CONFIG['HOST_NAME'], 
                                                Port              = CONFIG['SMTP_PORT_NUMBER'], 
                                                OutgoingQueues    = SMTPServer_OutgoingQueues,
                                                Config            = CONFIG,
                                                OnlyAllowSentFrom = splitemails2list(CONFIG['SMTP_ONLY_ALLOW_SENT_FROM']),
                                                Debug             = True)
                SMTPServer_Thread.start()
                threads.append(SMTPServer_Thread)              
            
            if CONFIG['DEEPSTACK_ENABLED']:
                from DeepStackClient import DeepStackClient as DeepStackClient_
                # Always pass output to Notification recorder
                DeepStackClient_Thread = DeepStackClient_(IncomingQueue  = DeepStackInQueue, 
                                                          OutgoingQueues = {'RecorderInQueue':RecorderInQueue},
                                                          Config         = CONFIG)
                DeepStackClient_Thread.start()
                threads.append(DeepStackClient_Thread)
            
            
            #Start Notification Recorder Service
            NotificationRecorder_Thread = NotificationRecorder_(IncomingQueue  = RecorderInQueue, 
                                                                OutgoingQueues = {'NotifierInQueue': NotifierInQueue}, 
                                                                DBconn         = DBconn, 
                                                                Config         = CONFIG)
            NotificationRecorder_Thread.start()
            threads.append(NotificationRecorder_Thread)
            
            #Start Telegram Notifier Service
            TelegramNotifier_Thread = TelegramNotifier_(config                   = CONFIG, 
                                                       db_conn                   = DBconn, 
                                                       camera_notification_queue = NotifierInQueue, 
                                                       direct_message_queue      = DirectMessageInQueue)
            TelegramNotifier_Thread.start()
            threads.append(TelegramNotifier_Thread)
            
            if CONFIG['HTTP_ENABLED']:
                from WebServer import WebServer as WebServer_
                WebServer_Thread = WebServer_(host = CONFIG['HOST_NAME'],
                                              port = CONFIG['HTTP_PORT_NUMBER'])
                WebServer_Thread.start()
                threads.append(WebServer_Thread)
 
            logger.critical(f'Server STARTED, Version {str(__version__)}, PID: {str(os.getpid())}\nSMTP Server on {CONFIG["HOST_NAME"]}:{CONFIG["SMTP_PORT_NUMBER"]}\nHTTP Monitoring on {CONFIG["HOST_NAME"]}:{CONFIG["HTTP_PORT_NUMBER"]}')
            
            test_notification_history = {}
            
            while True:
                try:    
                    menu = ConsoleMenu(f'ON PATROL SERVER V{str(__version__)} BUILD:{__build__} (PID:{xstr(os.getpid())})', 
                                       f'Server Name: {CONFIG["SERVER_LONG_NAME"]}',
                                       prologue_text=(get_status_message(CONFIG, log_level)),
                                       exit_option_text='Shutdown Server')
                    menu.append_item(ExitItem('Reload Config'))
                    menu.append_item(ExitItem('Send Test Notification'))
                    menu.append_item(ExitItem('View Loaded Telegram Groups'))
                    menu.append_item(ExitItem('View Live Log Output'))
                    
                    if logger.level > logging.DEBUG:
                        menu.append_item(ExitItem('Turn Debug Logging On'))
                    else:
                        menu.append_item(ExitItem('Turn Debug logging Off'))
                     
                    menu.show()
                    menu.join()
                    selection = menu.selected_option
                    
                    if selection == 0:
                        print(f'Server Name: {CONFIG["SERVER_LONG_NAME"]}' + '\nreloading config...')
                        reload_config(online_reload=True)
                    elif selection == 1:
                        if log_level > logging.DEBUG:
                            toggle_loglevel(all_log_handlers, log_level)
                        send_test_notification(listener, stream_handler, log_level, SMTPServer_OutgoingQueues , test_notification_history)
                        if log_level <= logging.DEBUG:
                            toggle_loglevel(all_log_handlers, log_level)
                    elif selection == 2:
                        show_telegram_groups_status()
                    elif selection == 3:
                        show_live_log(listener, stream_handler, log_level)
                    elif selection == 4:
                        log_level = toggle_loglevel(all_log_handlers, log_level)
                    elif selection == 5:
                        if PromptUtils(Screen()).confirm_answer('', message=f'Server Name: {CONFIG["SERVER_LONG_NAME"]}' + '\nAre you sure you want to shutdown the server?'):
                            break
                except KeyboardInterrupt:
                    if PromptUtils(Screen()).confirm_answer('', message=f'Server Name: {CONFIG["SERVER_LONG_NAME"]}' + '\nAre you sure you want to shutdown the server?'):
                        break
        finally:
            print('Please wait while the server shuts down safely...')
            logger.critical('Shutting down...')
            for thread in threads:
                try:
                    thread.stop()
                except:
                    pass
            DBconn.close()
            listener.handlers[-1].setLevel(logging.INFO)
            logger.critical('Server TERMINATED')
            listener.stop()

            if os.path.isfile(LOCKFILE):   
                os.remove(LOCKFILE)

    except (SystemExit):
        logger.critical('Server TERMINATED unexpectedly')
        listener.stop()
        pass


if __name__ == '__main__':
    main()