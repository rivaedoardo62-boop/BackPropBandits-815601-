"""Risposte JSON:API sintetiche, con la stessa struttura verificata su filings.xbrl.org."""

LEI_A = "BUCRF72VH5RBN7X3VL35"
LEI_B = "8156001A772766DCAA71"


def filing(fid, lei, period_end, seq=0, json_name=None, sha="a" * 64, date_added="2025-04-15 12:00:00", entity_id="1"):
    base = f"/{lei}/{period_end}/ESEF/IT/{seq}"
    json_name = json_name if json_name is not None else f"{lei}-{period_end}-it"
    return {
        "type": "filing",
        "id": str(fid),
        "attributes": {
            "fxo_id": f"{lei}-{period_end}-ESEF-IT-{seq}",
            "error_count": 0,
            "warning_count": 1,
            "inconsistency_count": 0,
            "processed": date_added,
            "date_added": date_added,
            "country": "IT",
            "period_end": period_end,
            "sha256": sha,
            "json_url": f"{base}/{json_name}.json" if json_name else None,
            "package_url": f"{base}/{lei}-{period_end}.zip",
            "report_url": f"{base}/{json_name}/reports/{json_name}.xhtml",
            "viewer_url": f"{base}/{json_name}/reports/ixbrlviewer.html",
        },
        "relationships": {"entity": {"data": {"type": "entity", "id": entity_id}}},
    }


def entity(entity_id, lei, name):
    return {"type": "entity", "id": entity_id, "attributes": {"name": name, "identifier": lei}}
