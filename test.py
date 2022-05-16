import time
import sys
from logging import DEBUG

from android_perf.log import default_stream_handler as logging_handler, default as logging
from android_perf.base_adb import AdbProxy
from android_perf.py_adb import PyAdb
from android_perf.pure_adb import PureAdb
from android_perf.adb_with_tools import AdbProxyWithToolsAll, AppInfo


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


def test_record(adb: AdbProxyWithToolsAll):
    adb.update_screen_record_settings(auto_stop_record=False)
    adb.start_screen_record()
    print('start screen record!')
    time.sleep(10)
    print('stop screen record!')
    adb.stop_screen_record()
    time.sleep(1)  # 等待保存视频


def test_netflow(adb: AdbProxyWithToolsAll, bundle: str = None):
    app = AppInfo()
    app.pkg = bundle
    adb.prepare_and_start_statistics_net_traffic(app)
    adb.go_back()
    time.sleep(0.1)
    print('\nstart app:', bundle)
    adb.launch_app(bundle)
    time.sleep(5)
    net = adb.finish2format_statistics_net_traffic()
    for n in net:
        print(f'Down:{n["down"]} # Up:{n["up"]}')
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
    with AdbProxy(py_adb) as _adb:
        get_perf(_adb, _app)

    with AdbProxy(PureAdb()) as _adb:
        print('pure-adb devices:', _adb.devices())
        get_perf(_adb, _app)

    with AdbProxyWithToolsAll(PureAdb()) as _adb:
        test_record(_adb)
        test_netflow(_adb, _app)
