# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [0.8.7] - 2019-10-06
### Added
- Python 3 compatibility for future OctoPrint release.
### Fixed
- ON/OFF comparison in cases where the response is not uppercase by default.
- Resolve issues with special characters in passwords.

## [0.8.6] - 2019-08-11
### Added
- configurable color options for the navbar icons.
- countdown timer that utilizes the backlog command with delay to allow for powering off a plug after the pi has been shutdown using the system command option.
- polling option to check status based on configured interval.

## [0.8.5] - 2018-03-12
### Added
- Show label text when TouchUI interface is enabled. Default UI should not see any change.
### Updated
- Screenshots for new settings interface.

## [0.8.4] - 2018-02-27
### Fixed
- Changed broken link to fontawesome icons.

## [0.8.3] - 2018-02-25
### Fixed
- Index setting restored after inadvertently being deleted.

## [0.8.2] - 2018-02-24
### Fixed
- Username/Password settings restored after inadvertently being deleted.

## [0.8.1] - 2018-02-03
### Fixed
- Icon not displaying in IE due to binding css issue.

## [0.8.0] - 2018-02-02
### Changed
- Improved settings layout to reduce clutter.

## [0.7.0] - 2018-02-01
### Fixed
- GCode off delay.

## [0.6.0] - 2018-01-14
### Fixed
- Single relay device issues

### Added
- single relay device option

### Notes
- single relay devices need to use 1 for index
- multiple relay devices need to disable the new option "Single Relay Device"

## [0.5.0] - 2018-01-11
### Notes
- previous settings will be erased during upgrade to accommodate for new features

### Added
- configurable icons using [fontawesome](http://fontawesome.io/3.2.1/cheatsheet/) class names in settings
- title attribute on icons are now configurable via new label setting

### Changed
- default value for index is now blank
- settings screenshot

## [0.4.0] - 2018-01-10
### Notes
- requires minimum Tasmota firmware version 5.9.0.

### Fixed
- status detection related to newer Tasmota software response being different

## [0.3.0] - 2018-01-04
### Fixed
- multiple relays not being detected properly

## [0.2.0] - 2017-12-03
### Added
- tasmota authentication when password is configured in the device's configuration other section.

### Notes
- previous settings will be deleted on upgrade due to authentication changes.
- username option was added in case it's incorporated later by tasmota. use admin for password or leave blank.
- passwords will be saved in pure text in config.yaml for this initial release.

## [0.1.0] - 2017-11-03
### Added
- Initial release.

[0.8.7]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.8.7
[0.8.6]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.8.6
[0.8.5]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.8.5
[0.8.4]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.8.4
[0.8.3]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.8.3
[0.8.2]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.8.2
[0.8.1]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.8.1
[0.8.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.8.0
[0.7.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.7.0
[0.6.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.6.0
[0.5.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.5.0
[0.4.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.4.0
[0.3.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.3.0
[0.2.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.2.0
[0.1.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.1.0
