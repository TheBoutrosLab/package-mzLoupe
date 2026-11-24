<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo/mzloupe-logo-on-navy.svg">
    <img src="docs/assets/logo/mzloupe-logo-on-light.svg" alt="mzLoupe" height="64">
  </picture>
</p>

# mzLoupe

**Explore mass spectrometry and proteomics data in your browser.**

Linked MS1 maps, spectra, precursor chromatograms, and filterable PSM tables help
you inspect evidence and troubleshoot results across samples and fractions.
Data stays on the machine running mzLoupe.

## Requirements

- Python 3.11 or newer; Python 3.12 is the tested development environment.
- A pyOpenMS wheel compatible with your Python version and platform.
- Node.js and npm for building from source. Node.js 22.12 or newer is recommended.

## Install from GitHub

```sh
git clone https://github.com/TheBoutrosLab/package-mzLoupe.git
cd package-mzLoupe
npm --prefix web ci
npm --prefix web run build
python -m pip install -e .
```

Run `mzloupe serve`, open http://127.0.0.1:8765, and add your files in
**Project setup**. mzML alone works; idXML adds identification evidence.

## Learn more

- [User guide](docs/user-guide.md): file setup, protein groups, plots, and filtering
- [Changelog](CHANGELOG.md)

Licensed under [BSD 3-Clause](LICENSE). Third-party dependencies retain their own licenses.

Copyright (C) 2026 Sanford Burnham Prebys Medical Discovery Institute ("Boutros Lab")
