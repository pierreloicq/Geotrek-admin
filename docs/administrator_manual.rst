======================
ADMINISTRATOR MANUAL
======================

Geotrek allows you to define some categories and settings for each module. They are available in Django Admin interface, only for superuser or staff members.

.. figure:: ./images/capture-admin.png
   :alt: Link to Admin

   Link to Admin

Some settings allows to add pictograms : recommended dimensions are the default pictograms dimensions.

Common settings
================

Theme

- Required
- Can be a sprite or an squared picto
- PNG, 64×64px

RecordSource

- Optional
- format and dimension ?

Infrastructure settings
========================

InfrastructureType

- Optional
- Default: `<static>/infrastructure/picto-infrastructure.png`
- format and dimension ?

Signage settings
========================

SignageType

- Optional
- Default: `<static>/signage/picto-signage.png`
- format and dimension ?

Trekking settings
================

TrekNetwork

- Required
- SVG, 36×36px (at least squared and viewbox dimension setted)

Practice

- Required
- SVG, 36×36px (at least squared and viewbox dimension setted)

Accessibility

- Optional
- PNG, 64×64px

Route

- Optional
- SVG, 36×36px (at least squared and viewbox dimension setted)

DifficultyLevel

- Optional
- SVG, 36×36px (at least squared and viewbox dimension setted)

WebLinkCategory

- Required
- PNG, 32×32px

POIType

- Required
- format and dimension ?

ServiceType


Diving settings
================

Practice

- Required
- SVG, 36×36px (at least squared and viewbox dimension setted)

Difficulty

- Optional
- format and dimension ?

Level

- Optional
- format and dimension ?

Tourism settings
================

InformationDeskType

- Required
- format and dimension ?

TouristicContentCategory

- Required
- SVG, 36×36px (at least squared and viewbox dimension setted)

TouristicContentType

- Optional
- format and dimension ?

TouristicEventType

- Optional
- format and dimension ?

Sensitivity settings
=====================

Species

- Optional
- format and dimension ?
