# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.2.0
[0.1.0]: https://github.com/jneilliii/OctoPrint-Tasmota/tree/0.1.0
