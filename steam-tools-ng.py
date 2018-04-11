#!/usr/bin/env python
#
# Lara Maia <dev@lara.click> 2015 ~ 2018
#
# The Steam Tools is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# The Steam Tools is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see http://www.gnu.org/licenses/.
#

import argparse
import asyncio
import logging
import os
import sys
import textwrap

if len(sys.argv) == 1:
    # noinspection PyUnresolvedReferences
    from ui import interface  # type: ignore # not implemented yet
else:
    from ui import console

from ui import config, logger

config.init()
logger.configure()

log = logging.getLogger(__name__)

if __name__ == "__main__":
    log.info('Steam Tools NG version 0.0.0-0 (Made with Girl Power <33)')
    log.info('Copyright (C) 2015 ~ 2018 Lara Maia - <dev@lara.click>')

    command_parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent('''
                Available modules for console mode:
                    - authenticator
                       '''))

    command_parser.add_argument('-c', '--cli',
                                choices=['authenticator'],
                                metavar='module [options]',
                                action='store',
                                nargs=1,
                                help='Start module without GUI (console mode)',
                                dest='module')
    command_parser.add_argument('options',
                                nargs='*',
                                help=argparse.SUPPRESS)

    console_params = command_parser.parse_args()

    if os.name == 'nt':
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)

    if console_params.module:
        module_name = f'on_start_{console_params.module[0]}'
        try:
            module_options = console_params.options[0]
        except IndexError:
            module_options = None

        assert hasattr(console, module_name), f'{module_name} doesn\'t exist in {console}'
        module = getattr(console, module_name)

        loop_ = asyncio.get_event_loop()
        return_code = loop_.run_until_complete(module(module_options))

        sys.exit(return_code)
    else:
        if os.name is 'posix' and not os.getenv('DISPLAY'):
            log.critical('The DISPLAY is not set!')
            log.critical('Use -c / --cli <module> for the command line interface.')
            sys.exit(1)

        program = interface.SteamTools()
        program.run()
