import time
import sys
from logging import DEBUG

from android_perf.log import default_stream_handler as logging_handler, default as logging
from android_perf.base_adb import AdbProxy
from android_perf.py_adb import PyAdb
from android_perf.pure_adb import PureAdb


def get_perf(adb: AdbProxy, bundle: str = None):
    print('\nsdk version:', adb.get_sdk_version())
    print('\ndevice info:', adb.get_device_info())
    print('\ndevice memory:', adb.get_device_memory())
    print('\ndevice cpu time:', adb.get_cpu_global())
    print('\ndevice netflow:', adb.get_device_traffic())
    if bundle:
        print('\nstart app:', bundle)
        adb.launch_app(bundle)
        time.sleep(0.1)
        main_pid = adb.find_main_process_id(bundle)
        start_traffic = adb.get_process_traffic(main_pid)
        time.sleep(2)
        pl = adb.find_process_ids(bundle)
        print('\napp memory:', adb.get_processes_memory(pl))
        print('\napp cpu time:', adb.get_processes_cpu_usage(pl))
        print('\napp netflow:', adb.compute_traffic_increase(start_traffic, adb.get_process_traffic(main_pid)))
        adb.kill_app(bundle)


def set_debug():
    logging_handler.setLevel(DEBUG)
    logging.setLevel(DEBUG)


if __name__ == '__main__':
    _app = len(sys.argv) > 1 and sys.argv[1] or None
    _debug = len(sys.argv) > 2
    if _debug:
        set_debug()
    py_adb = PyAdb(auto_connect=False)
    print('py-adb devices:', py_adb.devices())
    py_adb.open_connect()
    with AdbProxy(py_adb) as _adb1:
        get_perf(_adb1, _app)

    with AdbProxy(PureAdb()) as _adb2:
        print('pure-adb devices:', _adb2.devices())
        get_perf(_adb2, _app)
