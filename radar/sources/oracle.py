"""Oracle HCM Recruiting (Candidate Experience): the public REST search behind
https://<tenant>.fa.<dc>.oraclecloud.com/hcmUI/CandidateExperience/en/sites/<site>
-- American Express, JPMorgan Chase, BNY, Nokia, Navy Federal (verified live 2026-10-02).

Watchlist slug: the host minus ".oraclecloud.com", then "/<site>": "egug.fa.us2/CX_1",
"jpmc.fa/CX_1001", "fa-evmr-saasfaprod1.fa.ocs/CX_1".
"""
from __future__ import annotations

import re
from urllib.parse import quote

from radar.errors import ConfigError
from radar.sources.ats import WindowedSource, parse_date
from radar.sources.registry import register

_SLUG_RE = re.compile(r"^([a-z0-9-]+\.fa(?:\.[a-z0-9]+)*)/([A-Za-z0-9_]+)$")


class OracleSource(WindowedSource):
    kind = "oracle"
    # campus titles often say neither: "2027 | Americas | New York | Engineering | Summer Analyst" (Goldman)
    queries = ("intern", "graduate", "summer", "2027")

    def __init__(self, company):
        match = _SLUG_RE.match(company.slug or "")
        if match is None:
            raise ConfigError(f"oracle company {company.name!r}: slug must be '<host>/site' "
                              f"(from https://<host>.oraclecloud.com/.../sites/<site>), got {company.slug!r}")
        self.host, self.site = f"{match.group(1)}.oraclecloud.com", match.group(2)
        super().__init__(company)

    def board_url(self):
        return f"https://{self.host}/hcmUI/CandidateExperience/en/sites/{self.site}"

    async def search(self, ctx, query):
        finder = f"findReqs;siteNumber={self.site},keyword={quote(query)},sortBy=POSTING_DATES_DESC,limit=25"
        url = (f"https://{self.host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
               f"?onlyData=true&expand=requisitionList&finder={finder}")
        data = await self._get_json(ctx, url)
        return {} if data is None else self._shape(lambda d: {
            str(r["Id"]): (r.get("Title") or "", f"{self.board_url()}/job/{r['Id']}", r.get("PrimaryLocation") or "",
                           parse_date(r.get("PostedDate")))
            for r in d["items"][0]["requisitionList"]
        }, data)


@register("oracle")
def factory(company, settings):
    return OracleSource(company)
