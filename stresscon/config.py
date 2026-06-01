"""Configuration loader for Stresscon Operations Suite.

Reads SharePoint credentials and connection settings from environment
variables or a .env file in the project root.
"""

import os
from dotenv import load_dotenv

load_dotenv()

SHAREPOINT_URL: str = os.getenv("SHAREPOINT_URL", "https://enconunited.sharepoint.com/sites/Stresscon")
SHAREPOINT_CLIENT_ID: str = os.getenv("SHAREPOINT_CLIENT_ID", "")
SHAREPOINT_CLIENT_SECRET: str = os.getenv("SHAREPOINT_CLIENT_SECRET", "")

# SharePoint list names
MAINTENANCE_LOGS_LIST: str = "Maintenance_Logs"
MAINTENANCE_ARCHIVE_LIST: str = "Maintenance_Historical"

# Default labor rate ($/hr) for Cost of Idleness calculations
DEFAULT_LABOR_RATE: float = float(os.getenv("DEFAULT_LABOR_RATE", "45.00"))

# Default production rate (units/hr) for lost-output estimates
DEFAULT_PRODUCTION_RATE: float = float(os.getenv("DEFAULT_PRODUCTION_RATE", "1.0"))
