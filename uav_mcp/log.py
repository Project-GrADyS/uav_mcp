import logging
import logging.config


def set_log_config(args):
    logging_config = {
        'version': 1,
        'formatters': {
            'console_formatter': {
                'format': f"[%(name)s-{args.sysid}] %(levelname)s - %(message)s"
            },
            'file_formatter': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            }
        },
        "handlers": {
            'console_handler': {
                'class': 'logging.StreamHandler',
                'formatter': 'console_formatter'
            },
            'file_handler': {
                'class': 'logging.FileHandler',
                'filename': args.log_path,
                'formatter': 'file_formatter'
            }
        },
        'loggers': {
            'COPTER': {
                'level': 'INFO',
                'handlers': ['file_handler']
            },
            "GRADYS_GS": {
                'level': 'INFO',
                'handlers': ['file_handler']
            }
        }
    }

    if "COPTER" in args.log_console:
        logging_config['loggers']["COPTER"]['handlers'].append('console_handler')
    if "GRADYS_GS" in args.log_console:
        logging_config['loggers']["GRADYS_GS"]['handlers'].append('console_handler')

    if "COPTER" in args.debug:
        logging_config['loggers']["COPTER"]['level'] = "DEBUG"
    if "GRADYS_GS" in args.debug:
        logging_config['loggers']["GRADYS_GS"]['level'] = "DEBUG"

    logging.config.dictConfig(logging_config)
