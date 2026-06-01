"""SharePoint client wrapper using Office365-REST-Python-Client.

Provides authenticated access to Stresscon's SharePoint lists
for maintenance log CRUD operations.
"""

import logging
from typing import Any, Optional

from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.client_context import ClientContext

from stresscon.config import (
    MAINTENANCE_LOGS_LIST,
    SHAREPOINT_CLIENT_ID,
    SHAREPOINT_CLIENT_SECRET,
    SHAREPOINT_URL,
)

logger = logging.getLogger(__name__)


class SharePointClient:
    """Wrapper around Office365 ClientContext for Stresscon SharePoint."""

    def __init__(
        self,
        url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        self.url = url or SHAREPOINT_URL
        self.client_id = client_id or SHAREPOINT_CLIENT_ID
        self.client_secret = client_secret or SHAREPOINT_CLIENT_SECRET
        self._ctx: Optional[ClientContext] = None

    def connect(self) -> "SharePointClient":
        """Authenticate to SharePoint using client credentials."""
        if not all([self.url, self.client_id, self.client_secret]):
            raise ValueError(
                "SharePoint URL, client ID, and client secret are required. "
                "Set SHAREPOINT_URL, SHAREPOINT_CLIENT_ID, and "
                "SHAREPOINT_CLIENT_SECRET environment variables."
            )
        credentials = ClientCredential(self.client_id, self.client_secret)
        self._ctx = ClientContext(self.url).with_credentials(credentials)
        # Verify connection
        web = self._ctx.web
        self._ctx.load(web)
        self._ctx.execute_query()
        logger.info("Connected to SharePoint: %s", web.properties["Title"])
        return self

    @property
    def ctx(self) -> ClientContext:
        if self._ctx is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._ctx

    def get_maintenance_logs(
        self, filters: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Pull items from the Maintenance_Logs list.

        Args:
            filters: OData $filter string (e.g. "SeverityLevel eq 'Critical'").

        Returns:
            List of log items as dictionaries.
        """
        sp_list = self.ctx.web.lists.get_by_title(MAINTENANCE_LOGS_LIST)
        query = sp_list.items
        if filters:
            query = query.filter(filters)
        query = query.get()
        self.ctx.execute_query()
        return [item.properties for item in query]

    def create_maintenance_log(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new item in Maintenance_Logs.

        Args:
            data: Dictionary of field internal names to values.

        Returns:
            The created item's properties.
        """
        sp_list = self.ctx.web.lists.get_by_title(MAINTENANCE_LOGS_LIST)
        item = sp_list.add_item(data)
        self.ctx.execute_query()
        logger.info("Created maintenance log item ID: %s", item.properties["Id"])
        return item.properties

    def update_maintenance_log(
        self, item_id: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Update an existing Maintenance_Logs item.

        Args:
            item_id: SharePoint list item ID.
            data: Dictionary of field internal names to updated values.

        Returns:
            The updated item's properties.
        """
        sp_list = self.ctx.web.lists.get_by_title(MAINTENANCE_LOGS_LIST)
        item = sp_list.get_item_by_id(item_id)
        for key, value in data.items():
            item.set_property(key, value)
        item.update()
        self.ctx.execute_query()
        logger.info("Updated maintenance log item ID: %s", item_id)
        return item.properties
