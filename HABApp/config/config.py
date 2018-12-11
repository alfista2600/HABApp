import logging
import logging.config
import re
import time
from pathlib import Path

import ruamel.yaml
from voluptuous import Schema, MultipleInvalid, Invalid
from watchdog.observers import Observer

from HABApp.util import SimpleFileWatcher, CallbackHelper
from .configentry import ConfigEntry, ConfigEntryContainer
from .default_logfile import get_default_logfile

def TimeZoneValidator(msg=None):
    __re = re.compile('[+-]\d{4}')
    def f(v):
        v = str(v)
        if __re.fullmatch(v):
            return v
        else:
            raise Invalid(msg or ( f"incorrect timezone ({v})! Example: +1000 or -1030"))
    return f


_yaml_param = ruamel.yaml.YAML(typ='safe')
_yaml_param.default_flow_style = False
_yaml_param.default_style = False
_yaml_param.width = 1000000
_yaml_param.allow_unicode = True
_yaml_param.sort_base_mapping_type_on_output = False


log = logging.getLogger('HABApp.Config')


class Directories(ConfigEntry):
    def __init__(self):
        super().__init__()
        self.logging = 'log'
        self.rules   = 'rules'


class Ping(ConfigEntry):
    def __init__(self):
        super().__init__()
        self.enabled = False
        self.item = ''
        self.interval = 10


class General(ConfigEntry):
    def __init__(self):
        super().__init__()
        self.timezone = '+1000'
        self._entry_validators['timezone'] = TimeZoneValidator()


class Connection(ConfigEntry):
    def __init__(self):
        super().__init__()
        self.host = 'localhost'
        self.port = 8080
        self.user = ''
        self.password = ''

        self._entry_kwargs['user'] = {'default' : ''}
        self._entry_kwargs['password'] = {'default' : ''}


class Openhab(ConfigEntryContainer):
    def __init__(self):
        self.ping = Ping()
        self.connection = Connection()
        self.general = General()


class Config:

    def __init__(self, config_folder : Path, shutdown_helper : CallbackHelper = None):
        assert isinstance(config_folder, Path)
        assert config_folder.is_dir(), config_folder
        self.folder_conf = config_folder

        # these are the accessible config entries
        self.directories = Directories()
        self.openhab = Openhab()

        # if the config does not exist it will be created
        self.__check_create_config()
        self.__check_create_logging()

        # folder watcher
        self.__folder_watcher = Observer()
        self.__folder_watcher.schedule(SimpleFileWatcher(self.__file_changed, file_ending='.yml'), str(self.folder_conf))
        self.__folder_watcher.start()

        #proper shutdown
        shutdown_helper.register_func(self.__folder_watcher.stop)
        shutdown_helper.register_func(self.__folder_watcher.join, last=True)

        #Load Config initially
        self.__file_changed('ALL')

    def __file_changed(self, path):
        if path == 'ALL' or path.name == 'config.yml':
            self.load_cfg()
        if path == 'ALL' or path.name == 'logging.yml':
            self.load_log()
        return None

    def __check_create_config(self):
        __file = self.folder_conf / 'config.yml'
        if __file.is_file():
            return None

        cfg = {}
        self.directories.insert_data(cfg)
        self.openhab.insert_data(cfg)

        print( f'Creating {__file.name} in {__file.parent}')
        with open(__file, 'w', encoding='utf-8') as file:
            _yaml_param.dump(cfg, file)

        time.sleep(0.1)
        return None


    def __check_create_logging(self):
        __file = self.folder_conf / 'logging.yml'
        if __file.is_file():
            return None

        print(f'Creating {__file.name} in {__file.parent}')
        with open(__file, 'w', encoding='utf-8') as file:
            file.write(get_default_logfile())

        time.sleep(0.1)
        return None

    def load_cfg(self):
        __cfg = self.folder_conf / 'config.yml'
        if not __cfg.is_file():
            return

        with open( __cfg, 'r', encoding='utf-8') as file:
            cfg = _yaml_param.load(file)
        try:
            _s = {}
            self.directories.update_schema(_s)
            self.openhab.update_schema(_s)
            cfg = Schema(_s)(cfg)
        except MultipleInvalid as e:
            log.error( f'Error loading config:')
            log.error( e)
            return

        self.directories.load_data(cfg)
        self.openhab.load_data(cfg)

        # make Path absolute for all directory entries
        for k, v in self.directories.iter_entry():
            __entry  = Path(v)
            if not __entry.is_absolute():
                __entry = self.folder_conf / __entry
                self.directories.__dict__[k] = __entry.resolve()

        if not self.directories.logging.is_dir():
            print( f'Creating log-dir: {self.directories.logging}')
            self.directories.logging.mkdir()

        log.debug('Loaded HABApp config')


    def load_log(self):
        if self.directories is None:
            return None

        _logfile = self.folder_conf / 'logging.yml'
        if not _logfile.is_file():
            return None

        with open(_logfile, 'r', encoding='utf-8') as file:
            cfg = _yaml_param.load(file)

        # fix filenames
        for handler, handler_cfg in cfg.get('handlers', {}).items():
            if 'filename' not in handler_cfg:
                continue

            #make Filenames absolute path in the log folder if not specified
            p = Path(handler_cfg['filename'])
            if not p.is_absolute():
                p = (self.directories.logging / p).resolve()
                handler_cfg['filename'] = str(p)

        #load prepared logging
        logging.config.dictConfig(cfg)
        log.debug('Loaded logging config')
