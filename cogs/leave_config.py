"""
cogs/leave_config.py — Leave Management Configuration
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.

Centralises all channel/role ID mappings and the startup resolver.
Imported as a module (not via star-import) so callers always read
the live global values after resolve_leave_config() has run.
"""

import logging

from Bots.config import SUBMIT_CHANNEL_ID_FALLBACK, EMP_ROLE_ID as _EMP_ROLE_ID_FALLBACK
from Bots.db_managers import discovery_db_manager as discovery

logger = logging.getLogger("Concord")

# ─── Name → channel/role name mappings ───────────────────────────────────────

_APPROVAL_CHANNEL_NAMES = {
    'architects':          'leave-architects',
    'site':                'leave-site',
    'cad':                 'leave-cad',
    'administration':      'leave-administration',
    'hr':                  'leave-hr',
    'pa':                  'leave-pa',
    'interns':             'leave-architects',       # Interns share architects channel
    'heads':               'leave-hr',               # Heads escalate to HR
    'project_coordinator': 'leave-hr',               # Project coordinators escalate to HR
}

_DEPARTMENT_ROLE_NAMES = {
    'architects':     'Architects',
    'site':           'Site',
    'cad':            'CAD',
    'administration': 'Administration',
    'interns':        'Interns',
}

_DIRECT_SECOND_APPROVAL_ROLE_NAMES = {
    'project_coordinator': 'Project Coordinator',
    'heads':               'Heads',
}

# ─── Hardcoded fallback IDs ───────────────────────────────────────────────────

_APPROVAL_CHANNELS_FALLBACK = {
    'architects':          1298229045229781052,
    'site':                1298229146228359200,
    'cad':                 1298229187865346048,
    'administration':      1298229241338662932,
    'hr':                  1283723426103562343,
    'pa':                  1283723484698120233,
    'interns':             1298229045229781052,
    'heads':               1283723426103562343,
    'project_coordinator': 1283723426103562343,
}
_DEPARTMENT_ROLES_FALLBACK = {
    'architects':     1281172225432752149,
    'site':           1285183387258327050,
    'cad':            1281172603217645588,
    'administration': 1281171713299714059,
    'interns':        1281195640109400085,
}
_DIRECT_SECOND_APPROVAL_ROLES_FALLBACK = {
    'project_coordinator': 1298230195991478322,
    'heads':               1281173876704804937,
}

# ─── Live config — populated by resolve_leave_config() on bot startup ─────────

SUBMIT_CHANNEL_ID       = SUBMIT_CHANNEL_ID_FALLBACK
EMP_ROLE_ID             = _EMP_ROLE_ID_FALLBACK
APPROVAL_CHANNELS       = dict(_APPROVAL_CHANNELS_FALLBACK)
DEPARTMENT_ROLES        = dict(_DEPARTMENT_ROLES_FALLBACK)
DIRECT_SECOND_APPROVAL_ROLES = dict(_DIRECT_SECOND_APPROVAL_ROLES_FALLBACK)


async def resolve_leave_config():
    """
    Queries discovery.db to resolve channel and role IDs by name.
    Called once at startup by LeaveCog.on_ready().
    Falls back to hardcoded IDs for any entry not found in the DB.
    """
    global SUBMIT_CHANNEL_ID, EMP_ROLE_ID, APPROVAL_CHANNELS, DEPARTMENT_ROLES, DIRECT_SECOND_APPROVAL_ROLES

    # Resolve submit channel
    resolved_submit = await discovery.get_channel_id_by_name('leave-application')
    if resolved_submit:
        SUBMIT_CHANNEL_ID = resolved_submit
        logger.info(f"[Leave Config] #leave-application → {resolved_submit}")
    else:
        logger.warning("[ERR-LV-001] [Leave Config] Channel 'leave-application' not found in discovery.db — using fallback ID")

    # Resolve employee role
    resolved_emp = await discovery.get_role_id_by_name('emp')
    if resolved_emp:
        EMP_ROLE_ID = resolved_emp
        logger.info(f"[Leave Config] @emp → {resolved_emp}")
    else:
        logger.warning("[ERR-LV-002] [Leave Config] Role 'emp' not found in discovery.db — using fallback ID")

    # Resolve approval channels
    for key, ch_name in _APPROVAL_CHANNEL_NAMES.items():
        resolved = await discovery.get_channel_id_by_name(ch_name)
        if resolved:
            APPROVAL_CHANNELS[key] = resolved
            logger.info(f"[Leave Config] #{ch_name} → {resolved}")
        else:
            logger.warning(f"[ERR-LV-003] [Leave Config] Channel '{ch_name}' not found in discovery.db — using fallback ID for '{key}'")

    # Resolve department roles
    for key, role_name in _DEPARTMENT_ROLE_NAMES.items():
        resolved = await discovery.get_role_id_by_name(role_name)
        if resolved:
            DEPARTMENT_ROLES[key] = resolved
            logger.info(f"[Leave Config] @{role_name} → {resolved}")
        else:
            logger.warning(f"[ERR-LV-004] [Leave Config] Role '{role_name}' not found in discovery.db — using fallback ID for '{key}'")

    # Resolve direct second-approval roles
    for key, role_name in _DIRECT_SECOND_APPROVAL_ROLE_NAMES.items():
        resolved = await discovery.get_role_id_by_name(role_name)
        if resolved:
            DIRECT_SECOND_APPROVAL_ROLES[key] = resolved
            logger.info(f"[Leave Config] @{role_name} → {resolved}")
        else:
            logger.warning(f"[ERR-LV-005] [Leave Config] Role '{role_name}' not found in discovery.db — using fallback ID for '{key}'")

    logger.info("[Leave Config] Configuration resolved from discovery.db.")
