# Runtime validation — October 20, 2026

This record documents the real-device validation reported by the maintainer after the candidate artifacts were published.

- **Date:** October 20, 2026
- **Device:** Meizu 21 Pro (`meizu21Pro`)
- **Software setup:** Current PixelOS setup used for the candidate
- **Result:** The candidate booted and operated normally on the device. No problems were observed during the reported validation.
- **Validation type:** User-reported real-device runtime validation

This record complements the automated static reports. It does not rewrite those reports or claim a reproduced test log that is not included in this repository.

`CONFIG_CFS_BANDWIDTH` and `CONFIG_CGROUP_PIDS` remain disabled. CPU and process limits provided by those options are therefore intentionally unavailable; this decision did not prevent the reported device validation from completing successfully.
