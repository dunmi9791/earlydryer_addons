# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import re

from odoo import models

from .earlydryer_branch import BOARD_SUBCHANNEL

BOARD_CHANNEL_RE = re.compile(r"^earlydryer_board_(\d+)$")


class IrWebsocket(models.AbstractModel):
    _inherit = "ir.websocket"

    def _build_bus_channel_list(self, channels):
        """Boards ask for ``earlydryer_board_<branch id>``; they get the
        branch's board channel only when the user works on that branch."""
        channels = list(channels)
        branch_ids = []
        for channel in list(channels):
            match = isinstance(channel, str) and BOARD_CHANNEL_RE.match(channel)
            if match:
                channels.remove(channel)
                branch_ids.append(int(match.group(1)))
        if branch_ids and self.env.user and not self.env.user.share:
            allowed = self.env.user._earlydryer_allowed_branches()
            for branch in allowed.filtered(lambda b: b.id in branch_ids):
                channels.append((branch.with_env(self.env), BOARD_SUBCHANNEL))
        return super()._build_bus_channel_list(channels)
