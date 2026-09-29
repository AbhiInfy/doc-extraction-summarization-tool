from __future__ import annotations

import os
from dataclasses import dataclass

HCM_LANDING_URL = "https://docs.oracle.com/en/cloud/saas/readiness/hcm.html"
ERP_LANDING_URL = "https://docs.oracle.com/en/cloud/saas/readiness/erp.html"
SCM_LANDING_URL = "https://docs.oracle.com/en/cloud/saas/readiness/scm.html"


@dataclass(frozen=True)
class Pillar:
    key: str
    label: str
    landing_url: str
    report_path: str
    report_file: str
    env_report_key: str


PILLARS = {
    "HCM": Pillar(
        key="HCM",
        label="Human Capital Management (HCM)",
        landing_url=HCM_LANDING_URL,
        report_path="/Custom/Module Implemented Report.xdo",
        report_file="Module Implemented Report_Module Implemented.xlsx",
        env_report_key="FUSION_BIP_REPORT_PATH",
    ),
    "Finance": Pillar(
        key="Finance",
        label="Enterprise Resource Planning (Finance)",
        landing_url=ERP_LANDING_URL,
        report_path="/Custom/Module Implemented Report Finance.xdo",
        report_file="Module Implemented Report_Finance.xlsx",
        env_report_key="FUSION_BIP_REPORT_PATH_FINANCE",
    ),
    "SCM": Pillar(
        key="SCM",
        label="Supply Chain & Manufacturing (SCM)",
        landing_url=SCM_LANDING_URL,
        report_path="/Custom/Module Implemented Report SCM.xdo",
        report_file="Module Implemented Report_SCM.xlsx",
        env_report_key="FUSION_BIP_REPORT_PATH_SCM",
    ),
}


def get_pillar(key: str) -> Pillar:
    return PILLARS.get(key) or PILLARS["HCM"]


def pillar_report_path(pillar: Pillar) -> str:
    return (os.getenv(pillar.env_report_key) or pillar.report_path).strip()
