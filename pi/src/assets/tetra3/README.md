# tetra3 Databases

Store local `tetra3` database files here.

Recommended files:

- `primary_database.npz`
  - built for the actual upward camera field of view
- `fallback_database.npz`
  - built for a slightly wider max FOV as a recovery option
- `default_database.npz`
  - copied from the tetra3 repo for reference / regression use
  - note: the bundled tetra3 default database is built for `max_fov=12` and is not the right primary choice for a `70 deg` camera

Track for each database:

- source catalog used
- max FOV used to build it
- camera / lens / resolution it is intended for
- tetra3 version used when generating it
