# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
