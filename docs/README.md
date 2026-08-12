# Controlel documentation

Controlel keeps its platform-independent core and Home Assistant adapter in one
repository, but releases them independently. The Python core uses versions and
annotated tags such as `controlel==0.6.0` and `core-v0.6.0`. The Home Assistant
integration uses the version in `custom_components/controlel/manifest.json`,
integration tags in the `vX.Y.Z` namespace, and an exact published core
dependency.

- [Architecture](ARCHITECTURE.md)
- [Development guide](development/DevelopmentGuide.md)
- [Release guide](development/ReleaseGuide.md)
- [Deployment](operations/Deployment.md)
- [Home Assistant installation](operations/HomeAssistantInstallation.md)
- [Home Assistant entity reference](operations/EntityReference.md)
- [Troubleshooting](operations/Troubleshooting.md)
- [Roadmap](architecture/07_Roadmap.md)
