"""Amazon Product Advertising API (PA-API 5) collector -- spec 4.2.

PA-API request signing (AWS SigV4) is intentionally delegated to the official
``paapi5-python-sdk``. This collector is disabled by default in ``sources.yaml``; when
enabled with credentials AND the SDK installed, it queries US offers by keyword. Without
the SDK it logs a skip so the pipeline continues.
Docs: https://webservices.amazon.com/paapi5/documentation/
"""

from __future__ import annotations

from typing import Any

from app import util
from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.observation import PriceObservation


class AmazonPaapiCollector(BaseCollector):
    key = "amazon_paapi"

    def collect(self, products: list[dict[str, Any]]) -> CollectResult:
        skip = self.preflight()
        if skip:
            return self.skip_result(skip)
        try:
            from paapi5_python_sdk.api.default_api import DefaultApi  # type: ignore
            from paapi5_python_sdk.models.partner_type import PartnerType  # type: ignore
            from paapi5_python_sdk.models.search_items_request import SearchItemsRequest  # type: ignore
            from paapi5_python_sdk.models.search_items_resource import SearchItemsResource  # type: ignore
        except Exception:
            return self.skip_result(
                "amazon_paapi: install optional dep `pip install paapi5-python-sdk` to enable"
            )

        import os

        result = CollectResult()
        api = DefaultApi(
            access_key=os.environ["AMAZON_PAAPI_ACCESS_KEY"],
            secret_key=os.environ["AMAZON_PAAPI_SECRET_KEY"],
            host=os.environ.get("AMAZON_PAAPI_HOST", "webservices.amazon.com"),
            region=os.environ.get("AMAZON_PAAPI_REGION", "us-east-1"),
        )
        partner_tag = os.environ["AMAZON_PAAPI_PARTNER_TAG"]
        for product in products:
            pid = product["product_id"]
            keyword = product.get("canonical_name_en")
            if not keyword:
                continue
            self._throttle()
            try:
                req = SearchItemsRequest(
                    partner_tag=partner_tag,
                    partner_type=PartnerType.ASSOCIATES,
                    keywords=keyword,
                    item_count=10,
                    resources=[
                        SearchItemsResource.ITEMINFO_TITLE,
                        SearchItemsResource.OFFERS_LISTINGS_PRICE,
                    ],
                )
                resp = api.search_items(req)
                items = getattr(getattr(resp, "search_result", None), "items", None) or []
            except Exception as exc:  # noqa: BLE001 - SDK raises many types
                result.logs.append(self.log("failure", message=str(exc)[:200], query=keyword))
                continue
            for it in items:
                title = getattr(getattr(getattr(it, "item_info", None), "title", None), "display_value", "")
                price = None
                listings = getattr(getattr(it, "offers", None), "listings", None) or []
                if listings:
                    price = util.as_float(getattr(getattr(listings[0], "price", None), "amount", None))
                result.observations.append(
                    PriceObservation(
                        run_id=self.run_id, product_id=pid, source_name="AmazonUS",
                        source_type="api", country="US", platform="AmazonUS",
                        listing_title=title, listing_id=getattr(it, "asin", ""),
                        currency="USD", price=price, availability_status="active",
                        match_confidence=self.match_confidence(pid, title),
                        confidence_level=ConfidenceLevel.API_VERIFIED.value,
                    )
                )
            result.logs.append(self.log("success", query=keyword, records=len(items)))
        return result
