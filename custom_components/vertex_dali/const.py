DOMAIN = "vertex_dali"

CONF_CONTROLLERS = "controllers"
CONF_ROOMS = "rooms"
CONF_GROUPS = "groups"
CONF_DEVICES = "devices"
CONF_SHORT_ADDRESS = "short_address"
CONF_DALI_PORT = "dali_port"
CONF_WRITE_REGISTER = "write_register"

DEFAULT_PORT = 502
DEFAULT_TIMEOUT = 1
DEFAULT_SCAN_INTERVAL = 1
DEFAULT_RETRIES = 3

# Vendor-documented, empirically confirmed formula (glamox.atlassian.net/wiki/spaces/ME,
# page "Luminaires registers map (table)") -- see memory.ai/vertex-individual-control.md.
# Each luminaire occupies a fixed 50-register Input Register block; only the
# offsets actually used here are read.
REGISTER_BASE = 400
REGISTER_STRIDE = 50
PORT_STRIDE = 3200
OFFSET_PACKED_LEVEL = 8   # high byte = PowerOnLevel, low byte = ActualLevel (raw DALI 0-254 log scale)
OFFSET_STATUS = 19        # 0=stale, 1=offline, 2=ok
READ_BLOCK_WORDS = 20     # covers every offset this integration decodes
