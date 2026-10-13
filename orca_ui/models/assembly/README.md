# Assembly model archives

The four complete assembly models are stored here as standard ZIP files:

- `base-left-dynamixel.zip`
- `base-right-dynamixel.zip`
- `touch-left-dynamixel.zip`
- `touch-right-dynamixel.zip`

Each archive contains one `assembly.glb`. Geometry is unchanged; ZIP compression
only reduces storage and transfer size. Small movement and supply meshes remain
in their existing locations.

The backend automatically restores these files before serving the UI. In a source
checkout it restores both locations, relative to the repository root:

```text
orca_ui/webui/assembly/parts/<configuration>/assembly.glb
frontend/public/assembly/parts/<configuration>/assembly.glb
```

An installed Python package restores only its packaged web UI. Extraction needs
write access to those asset directories. Failures are logged without blocking
the rest of the console; the opening model viewer provides recovery instructions.
All paths are resolved from the package location, independent of the launch directory.

The extracted GLBs and their `.assembly-model.json` validation markers are ignored
by Git. Do not add them back with `git add -f`. An unchanged model is not extracted
again; a missing, modified or outdated output is restored from its archive. ZIP
integrity is checked during extraction, and files are replaced atomically.

To restore manually, run this from the repository root:

```sh
uv run python -m orca_ui.assembly_assets
```

Alternatively, unzip a named archive into its configuration directory above.
When running Vite, restore the `frontend/public` copy too. Click **Retry model**
or reload the guide afterward. The complete models are not available for Full
or FeeTech; extracting these archives does not add those configurations.

After intentionally editing/regenerating the source GLBs, update the archives
**before restarting the backend**, since startup restores the archived version:

```sh
python scripts/package_assembly_models.py
uv run python -m orca_ui.assembly_assets
```

The packaging script reads the four source models under `frontend/public`, writes
one ZIP per configuration and refuses an archive of 100 MiB or larger. Review and
commit the ZIPs with corresponding inventory, route and scene changes. Keep archives
and their metadata from the same CAD revision.

Ignoring or untracking a file does not remove it from earlier Git commits. If a
push is rejected because an earlier unpublished commit contains an oversized GLB,
that history needs a separately reviewed cleanup; the ZIP migration does not rewrite it.
