## verdict

1. Resolved — app.js:59 now emits occurred_at.required only for incident, so editing saved service_request/inquiry fields no longer restores the erroneous requirement. The supplied Playwright assertions cover empty time through preview→내용 수정→preview for both non-incident types and confirm that incident still blocks an empty time. All 11 same-path recaptures were reopened and are valid; no visible regression from this conditional-field fix was found. This ship verdict covers the scored fix only.

## remaining

Clear.

disposition: ship
