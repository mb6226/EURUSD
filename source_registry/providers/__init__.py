"""Official external-provider acquisition modules; network calls require explicit invocation."""

from .bls import BLSCPIRecordsProvider
from .cftc import CFTCOfficialSnapshotProvider
from .ecb_sdmx import ECBSdmxHistoricalProvider
from .fred import FREDALFREDVintageProvider

__all__ = ["BLSCPIRecordsProvider", "CFTCOfficialSnapshotProvider",
           "ECBSdmxHistoricalProvider", "FREDALFREDVintageProvider"]
