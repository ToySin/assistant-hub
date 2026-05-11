"""Shared Google Application Default Credentials helper.

Used by library/sources/gdrive_gemini.py, library/sources/gcal.py, and
library/sources/gmail.py. Extracts the ADC bearer token + active GCP
project via gcloud CLI so we don't need the google-auth Python package.

One-time setup (run once per laptop):
  gcloud auth application-default login \
    --scopes=openid,\
https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/calendar.readonly,\
https://www.googleapis.com/auth/drive.readonly,\
https://www.googleapis.com/auth/gmail.readonly
"""

from __future__ import annotations

import shlex
import subprocess


def gcloud_token() -> tuple[str, str]:
    """Return (bearer_token, gcp_project) from Application Default Credentials.

    Raises RuntimeError with actionable instructions if gcloud is missing
    or ADC hasn't been configured.
    """
    try:
        token = subprocess.check_output(
            shlex.split("gcloud auth application-default print-access-token"),
            stderr=subprocess.PIPE, text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(
            "Google ADC token unavailable. Run once:\n"
            "  gcloud auth application-default login \\\n"
            "    --scopes=openid,"
            "https://www.googleapis.com/auth/userinfo.email,"
            "https://www.googleapis.com/auth/cloud-platform,"
            "https://www.googleapis.com/auth/calendar.readonly,"
            "https://www.googleapis.com/auth/drive.readonly,"
            "https://www.googleapis.com/auth/gmail.readonly"
        ) from exc
    try:
        project = subprocess.check_output(
            shlex.split("gcloud config get-value project"),
            stderr=subprocess.PIPE, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        project = ""
    return token, project


def headers(auth: str | None = None) -> dict:
    """Return Authorization + quota-project headers.

    If `auth` is provided (from auth_env in sources.yaml) it is used as
    the Bearer token directly, skipping the ADC subprocess call. Falls
    back to ADC otherwise.
    """
    if auth:
        token, project = auth, ""
    else:
        token, project = gcloud_token()
    h = {"Authorization": f"Bearer {token}"}
    if project:
        h["x-goog-user-project"] = project
    return h
