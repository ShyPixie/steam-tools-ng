#!/usr/bin/env python
#
# Lara Maia <dev@lara.monster> 2015 ~ 2020
#
# The Steam Tools NG is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# The Steam Tools NG is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see http://www.gnu.org/licenses/.
#
import asyncio
import logging
import random

import aiohttp
from stlib import client, webapi, plugins

from . import utils
from .. import config, i18n

log = logging.getLogger(__name__)
_ = i18n.get_translation


async def run(plugin_manager: plugins.Manager) -> int:
    api_url = config.parser.get('steam', 'api_url')
    steamid = config.get("login", "steamid")
    session = utils.http_session()
    webapi_session = webapi.SteamWebAPI(session, api_url)
    time_offset = await config.time_offset(webapi_session)
    steam_login_status = await utils.check_login(session, webapi_session, time_offset)

    if not steam_login_status:
        return 1

    while True:
        log.info(_("Loading"))
        reverse_sorting = config.parser.getboolean("cardfarming", "reverse_sorting")
        wait_min = config.parser.getint("cardfarming", "wait_min")
        wait_max = config.parser.getint("cardfarming", "wait_max")

        log.info(_("Waiting Steam Server"))

        try:
            badges = sorted(
                await webapi_session.get_badges(steamid),
                key=lambda badge_: badge_.cards,
                reverse=reverse_sorting
            )
        except aiohttp.ClientError:
            log.error(_("No Connection"))
            await asyncio.sleep(10)
            continue

        if not badges:
            break

        for badge in badges:
            wait_offset = random.randint(wait_min, wait_max)

            while badge.cards != 0:
                print(_("Running"), f"{badge.game_name} ({badge.game_id})")
                executor = client.SteamApiExecutor(badge.game_id)

                while True:
                    try:
                        await executor.init()
                        break
                    except client.SteamAPIError:
                        log.error(_("Invalid game_id %s. Ignoring."), badge.game_id)
                        # noinspection PyProtectedMember
                        badge = badge._replace(cards=0)
                        break
                    except ProcessLookupError:
                        log.error(_("Steam Client is not running."))
                        await asyncio.sleep(5)

                for past_time in range(wait_offset):
                    print(_("Waiting drops for {:4d} minutes").format(round((wait_offset - past_time) / 60)),
                          end='\r')

                    await asyncio.sleep(1)

                print(_("Updating drops for {} ({})").format(badge.game_name, badge.game_id), end='\r')
                await executor.shutdown()
                await asyncio.sleep(60)

                while True:
                    try:
                        badge = await webapi_session.update_badge_drops(badge, steamid)
                        break
                    except aiohttp.ClientError:
                        log.error(_("No connection"))
                        await asyncio.sleep(10)

            print(_("Done"), f"{badge.game_name} ({badge.game_id})", end='\r')

        log.info(_("No more cards to drop. Searching new..."))

    return 0
