# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.10.1] - 2026-11-10

### Fixed

- The container installed its dependencies with `pip install .`, which reads
  only `pyproject.toml`'s floor-pins and resolves fresh at build time -- a
  dependency set no test had ever run against. The image now installs from
  the committed, Dependabot-maintained `uv.lock` via a frozen `uv export`, so
  the shipped versions are the ones CI tested. Same bug as mcp-gemini PR #72
  and trentina issue #79 (RT #1564).

## [0.10.0] - 2026-11-09

### Fixed

- **A response had no size limit at all.** `statusjson.cgi` on a wide query, or
  anything else answering on that URL, was read whole into the process. Bodies
  are now read in bounded pieces under a 10MB cap, measured before each chunk
  is copied in, and the error says to narrow the query — which is how this gets
  hit in practice.

- **An error says which site answered, and with what.** A non-200 raised
  `response.text[:200]` with no method, URL, status or content-type, and this
  client follows redirects: a CGI behind an SSO proxy answers from somewhere
  else entirely, and a bare 200 characters of HTML cannot say so. Errors now
  name all four and quote a bounded snippet.

- **A non-JSON body is reported as one.** `response.json()` on an HTML page
  raised a bare decode error — the RT #1596 shape.

### Added

- **The client says what it is.** Requests carry
  `User-Agent: mcp-nagios-crunchtools/<version> (+<repo url>)`, with the
  version read from installed package metadata.

### Changed

- All three call sites — `statusjson.cgi`, `archivejson.cgi` and `cmd.cgi` —
  go through one `_request`. Three copies of the transport handling is how this
  module ended up with no ceiling in any of them.

- Inherits constitution v1.36.0, whose MCP Server profile 1.8.0 states the
  outbound HTTP contract (RT #1601).

## [0.9.1] - 2026-11-07

### Fixed

- `nagios_list_downtimes` and `nagios_cancel_downtime` now survive a downtime
  entry Nagios cannot render. The details query is still one request; when it
  crashes, the list is read again as ids (`details=false` renders no stored
  string, so it cannot crash) and each id is fetched on its own. One bad
  comment now costs that one entry instead of every tool that reads downtime,
  so a window scheduled alongside it can still be listed and cancelled.
  `nagios_list_downtimes` counts the entry it could not render and names its
  id rather than implying no downtime is there.
- `nagios_cancel_downtime` leaves an unrenderable entry alone and says so. Its
  author cannot be read, and the author filter is what makes pointing the tool
  at a host safe; in steady state every window this server opens has an ASCII
  comment, so an unrenderable one was opened by a person. `nagios_downtime_history`
  names who opened it.
- `NagiosCgiCrashError` is now raised only when the downtime id list itself
  crashes, which no stored comment can cause, so it means the JSON CGI is
  broken outright rather than holding one bad comment. A single unrenderable
  entry is skipped and named instead.
- `NagiosQueryError` carries the CGI's own `type_code`, so a caller can tell
  one query failure from another. The per-id downtime read uses it to treat
  only "the id is unknown" as a window that ended between the two calls;
  every other query failure is raised rather than silently dropping the entry
  from the listing.
- The per-id downtime reads run a few at a time. One `statusjson.cgi` request
  is one CGI process reading the whole status file, so a host with many
  windows would otherwise have forked one per entry at once.
- A downtime id the CGI does not report as a number is now an error. It used
  to be skipped, which hid the window -- the failure this release exists to
  fix.

## [0.9.0] - 2026-11-07

### Fixed

- Comments are folded to ASCII before they are submitted, so a character
  outside ASCII can no longer take down `nagios_list_downtimes` and
  `nagios_cancel_downtime`. Nagios 4.5.9's `statusjson.cgi` aborts in
  `__mbstowcs_chk` and dumps core while rendering such a comment, and because
  the crash kills the read that `nagios_cancel_downtime` depends on, the
  offending comment could not be removed until it expired. Punctuation that
  carries meaning is spelled out (`--`, `...`, `->`, `>=`) rather than dropped,
  and an accented letter keeps its base letter. A comment with no ASCII reading
  at all is rejected at validation with a message saying why.
  (crunchtools/mcp-nagios#65)
- An HTTP 500 from the JSON CGI now raises `NagiosCgiCrashError`, which names
  the query that crashed, the non-ASCII comment as the known cause, and
  `nagios_downtime_history` as the way to read downtime meanwhile. It used to
  surface as a bare `Nagios API error 500` carrying an Apache HTML page, which
  read as a Nagios outage rather than as one bad comment. Other HTTP errors
  are unchanged.

## [0.8.2] - 2026-10-31

### Security

- Upgraded locked dependencies within their declared ranges to clear the
  advisories the fleet dependency audit found (authlib, dnspython, joserfc, opentelemetry-api, pyjwt).

## [0.8.1] - 2026-10-26

### Fixed

- `nagios_downtime_history` no longer reports a window as ongoing when its
  scheduled end has passed but the log has no STOPPED for it, which happens
  when Nagios restarts inside the window.

## [0.8.0] - 2026-10-26

### Added

- `nagios_schedule_downtime` puts a host and all its services, or one service,
  into fixed downtime starting now, for 5 to 480 minutes, before planned work
  makes checks fail. `nagios_list_downtimes` shows what is in effect or pending,
  and `nagios_cancel_downtime` ends this server's own downtime (never another
  author's) when the work is done.
- `nagios_downtime_history` lists past and current downtime windows with their
  author and comment. archivejson.cgi never returns downtime entries, so this
  reads `nagios.log` from the new optional `NAGIOS_LOG_PATH`.
- `nagios_host_status` and `nagios_service_status` report `In Downtime`.

### Changed

- `nagios_alert_history` leaves problems raised inside a downtime window for
  that object out of the per-object lines and totals them on a final "plus N
  event(s) ... during scheduled downtime" line, so planned work stops ranking as
  noise. Without `NAGIOS_LOG_PATH` it behaves as before.

### Removed

- A stray `tools/history.py.conflict1` left over from a merge.

## [0.7.0] - 2026-10-21

### Added

- `NAGIOS_CGI_PREFIX` sets the CGI path under `NAGIOS_URL`, for Nagios served
  somewhere other than `/nagios/`. It defaults to `/nagios/cgi-bin`, so existing
  setups are unchanged. A trailing slash is ignored.

## [0.6.0] - 2026-10-20

### Changed

- Container base images pinned to `quay.io/hummingbird/python:3.14*` instead of
  `latest`, which moved to Python 3.15.0 on 2026-10-20 (crunchtools/constitution#66).

## [0.5.0] - 2026-10-16

### Added
- `NAGIOS_COMMENT_AUTHOR` sets the author recorded on acknowledgements and
  comments. It falls back to `NAGIOS_USER`. It is deliberately not a tool
  parameter, so the caller cannot choose whose name goes on the record.

### Changed
- The read tools publish their bounds in the tool schema (`hours` 1 to 744, host
  and service name lengths, `max_staleness_seconds` at least 1), so a client can
  reject a bad value, such as a negative `hours`, before calling.

### Fixed
- Acknowledgements and comments were always authored by the fixed string
  "Hermes".

## [0.4.1] - 2026-10-10

### Fixed
- Host alerts and host notifications were all attributed to "unknown host", which
  merged every host's alerts into one row of `nagios_alert_history_tool`.
  `archivejson.cgi` names the host in `name` on a host entry and in `host_name`
  on a service entry.

## [0.4.0] - 2026-10-10

### Added
- `nagios_alert_history_tool` rolls up the alert log per host and service over a
  period (default one week): how many problem events, in which states, how many
  hard, first and last time, the last state seen, and the last problem output.
  Notifications fire only on what Nagios pages for, so warnings and problems that
  recovered by themselves were invisible until now.
- `nagios_current_problems_tool` reports, for each problem, how long it has been
  in that state, soft or hard with the attempt count, whether it is acknowledged
  or in downtime, and the plugin output.
- Both history tools validate their input: `hours` from 1 to 744 (one month) and
  a host name of at most 255 characters.

### Fixed
- `nagios_notification_history_tool` named every row "Service unknown". It read a
  `name` field that `archivejson.cgi` does not return; the host is in `host_name`
  and the service in `description`.

## [0.3.0] - 2026-10-10

### Added
- The five tools that only read (`nagios_host_status_tool`,
  `nagios_service_status_tool`, `nagios_current_problems_tool`,
  `nagios_program_status_tool`, `nagios_notification_history_tool`) publish
  `readOnlyHint: true`. A gateway uses it to decide whether an invalid optional
  argument may be dropped or must refuse the call (crunchtools/constitution#35).
  The three tools that submit an external command through `cmd.cgi`
  (acknowledge, add comment, schedule check) stay unannotated.
- Tests pin every registered tool into `READ_ONLY` or `WRITES`, and check that
  each read-only tool sends Nagios nothing but GET requests, none of them to
  `cmd.cgi`.

### Changed
- Inherits constitution v1.22.0; the workflow pins and the pre-commit hook rev
  move with it.
- Constitution is now a v1.18.0 manifest; constitution validation is pinned
  through `constitution.yml`, and Dependabot auto-merges GitHub Actions
  minor/patch updates.

## [0.2.0] - 2026-09-19

### Added
- **`nagios_program_status_tool`** — a health check on the monitoring path
  itself, deliberately separate from the state of the things Nagios monitors.
  Queries `statusjson.cgi?query=programstatus` and catches three failures that
  `nagios_current_problems` cannot see: a wedged daemon (Apache still serves the
  CGI with HTTP 200 while status data stops advancing, so problems are reported
  from frozen data), notifications globally disabled (Nagios checks everything
  and tells nobody, and looks perfectly healthy doing it), and a stale status
  file.

  The Kagetora watchdog had been using `nagios_current_problems` as a liveness
  proxy, which meant it could not detect the failure it exists to detect —
  "no current problems" is the answer both when everything is fine and when
  Nagios has silently stopped working. It also drifted into re-alerting on
  CRITICALs the push path had already delivered.

## [0.1.2] - 2026-09-19

### Fixed
- **Forced checks were queued four hours into the future.** `cmd.cgi` parses
  `start_time` as naive wall-clock in the Nagios server's own timezone — the form
  carries no offset field — and `schedule_check` was sending `time.gmtime()`.
  The mcp-nagios container runs UTC while the Nagios server runs EDT, so every
  forced check reported success and then did nothing. Now `time.localtime()`,
  with a regression test that pins `TZ=America/New_York` and asserts the
  submitted `start_time` is local wall-clock rather than UTC.

  Note the deployment half: `localtime()` in a UTC container still yields UTC.
  The container must share the Nagios server's timezone via a bind-mounted
  `/etc/localtime:ro`.
- **PENDING hosts and services were reported as problems.** A not-yet-checked
  service has `has_been_checked=0`, which Nagios itself treats as PENDING, not
  UNKNOWN. `nagios_current_problems` was reporting healthy services as outages.

## [0.1.0] - 2026-08-23

Initial tagged release. No GitHub Release was created for this tag, so no
authored release notes exist to back-fill from; this changelog starts here
(RT #1484).
