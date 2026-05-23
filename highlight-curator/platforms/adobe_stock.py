"""Adobe Stock Contributor API client. Uses stdlib only."""
import json
import uuid
from pathlib import Path
from urllib import request as urlreq
from urllib.parse import urlencode

IMS_BASE   = "https://ims-na1.adobelogin.com"
STOCK_BASE = "https://stock.adobe.com/Rest/Media/1/Files"


class AdobeStockClient:
    def __init__(self, api_key: str, client_secret: str, access_token: str = ""):
        self.api_key      = api_key
        self.client_secret = client_secret
        self.access_token = access_token

    def refresh_token(self) -> None:
        data = urlencode({
            "grant_type":    "client_credentials",
            "client_id":     self.api_key,
            "client_secret": self.client_secret,
            "scope":         "openid,AdobeID,stock_contributor",
        }).encode()
        req = urlreq.Request(
            f"{IMS_BASE}/ims/token/v3",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlreq.urlopen(req) as r:
            self.access_token = json.loads(r.read())["access_token"]

    def upload(self, image_path: Path, metadata: dict) -> dict:
        if not self.access_token:
            self.refresh_token()
        body, ct = _build_multipart(
            {"title":    metadata.get("title", ""),
             "keywords": metadata.get("keywords", "")},
            "file", image_path,
        )
        req = urlreq.Request(
            STOCK_BASE,
            data=body,
            headers={"Authorization": f"Bearer {self.access_token}",
                     "x-api-key": self.api_key,
                     "Content-Type": ct},
        )
        with urlreq.urlopen(req) as r:
            return {"asset_id": str(json.loads(r.read()).get("id", ""))}

    def get_status(self, asset_id: str) -> str:
        try:
            if not self.access_token:
                self.refresh_token()
            req = urlreq.Request(
                f"{STOCK_BASE}/{asset_id}",
                headers={"Authorization": f"Bearer {self.access_token}",
                         "x-api-key": self.api_key},
            )
            with urlreq.urlopen(req) as r:
                return json.loads(r.read()).get("status", "unknown")
        except Exception:
            return "unknown"


def _build_multipart(fields: dict, file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "GTNboundary" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
             f"{value}\r\n").encode()
        )
    file_bytes = file_path.read_bytes()
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\";"
         f" filename=\"{file_path.name}\"\r\nContent-Type: image/jpeg\r\n\r\n").encode()
        + file_bytes + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
