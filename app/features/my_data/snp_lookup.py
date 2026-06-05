from __future__ import annotations

from app.features.matching.domain import SnpLookupResult, lookup_snp_in_raw

from .storage import MyDataStore, SampleAsset


def lookup_snp_in_sample(
    store: MyDataStore,
    user_id: int,
    sample: SampleAsset,
    rsid: str,
) -> SnpLookupResult:
    raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        return SnpLookupResult(
            rsid=rsid.strip().lower(),
            chromosome=None,
            position=None,
            genotype="--",
            found=False,
            error="no_raw",
        )
    return lookup_snp_in_raw(store.resolve_raw_file_path(raw_file), rsid)
