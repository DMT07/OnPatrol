import threading, asyncio, datetime, sys

from aiohttp import web
from Common import aioEvent_ts #a thread safe asyncio.Event class
import logging



logger = logging.getLogger('patrol_bot')

@web.middleware
async def handle_error_middleware(request, handler):
    try:
        response = await handler(request)
        return response
    except web.HTTPException as ex:
        return web.Response(text = ex.text, status=ex.status)
    except Exception:
        return web.Response(text = '500 Internal Server Error', status=500)

def remove_aiohttp_stderr_logging():
    sys_logger_names = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    aiohttp_logger_names = ['aiohttp.access', 
                            'aiohttp.client', 
                            'aiohttp.internal',
                            'aiohttp.server',
                            'aiohttp.web',
                            'aiohttp.websocket']
    for _logger in [name for name in aiohttp_logger_names if name in sys_logger_names]:
        try:
            _logger.removeHandler(sys.stderr)
        except:
            pass

async def handle_get_running(request):
    return web.Response(text='Running '+datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


async def start_site(runners, app, host='0.0.0.0', port=8080):
    runner = web.AppRunner(app)
    runners.append(runner) #To keep a record of this web app
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
        
    logger.info(f' [WebServer]        Started on port {str(port)}')
                   
async def web_server_main(host, port, exit_flags):
    try:
        loop = asyncio.get_running_loop()
    except:
        loop = asyncio.new_event_loop()
    exit_flag = aioEvent_ts()
    exit_flags.append(exit_flag)
    runners = [] #To keep a record of the running web apps

    webapp = web.Application(logger=logger,middlewares=[handle_error_middleware])
    webapp.add_routes([web.get('/', handle_get_running)])
    loop.create_task(start_site(runners, webapp, host, port))
    remove_aiohttp_stderr_logging()    
    await exit_flag.wait()

    try:
        await exit_flag.wait()
    finally:
        for runner in runners:
            await runner.cleanup()

class WebServer(threading.Thread):
    def __init__(self, host, port):    
        threading.Thread.__init__(self)
        self.name = 'WebServer'
        self.exit_flags = []
        self.host = host
        self.port = port

    def run(self):
        asyncio.run(web_server_main(host      = self.host,
                                    port      = self.port,
                                    exit_flags = self.exit_flags))
    
    def stop(self):
        for flag in self.exit_flags:
            flag.set()
        self.join()    
        logger.debug(' [WebServer]        Stopped')
    
    
    
    
    
    
    
    