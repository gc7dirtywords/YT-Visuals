# Phase 9 Repository Context Snapshot

Generated: 2026-09-22T14:02:46.6960301-04:00
Repo: D:\YT-Visuals

## Git

```text
D:/YT-Visuals
9877c1669f2fc01a92f4ded9e0e5dda3793c4f8a
?? Tools/codex_context_snapshot.ps1
?? Tools/migrate_windows_to_unraid.py
?? docs/Codex/
?? tests/test_unraid_migration.py
9877c16 fix: support cross-filesystem media finalization
4427655 fix: support independent server storage roots
e3591c6 fix: harden Pexels media downloads
2169ea7 feat: add YT-ChannelOps application icon
fa7391b fix: correct GHCR publish workflow
```

## Top-level layout

```text

Mode  Length LastWriteTime         Name
----  ------ -------------         ----
d--h-        9/22/2026 2:02:46 PM  .git
d----        8/30/2026 6:04:05 PM  .github
d----        8/16/2026 7:44:47 PM  .pytest_cache
d----        8/16/2026 7:37:38 PM  .venv
d----        8/30/2026 6:42:50 PM  assets
d----        8/30/2026 6:04:42 PM  Data
d----        9/22/2026 1:58:09 PM  docs
d----        8/25/2026 9:14:07 PM  examples
d----        8/29/2026 3:36:16 PM  Library
d----        8/16/2026 7:45:19 PM  migrations
d----        8/30/2026 10:25:42 AM Projects
d----        8/29/2026 3:28:39 PM  schemas
d----        8/16/2026 7:44:12 PM  src
d----        8/30/2026 10:40:53 AM Temp
d----        8/30/2026 6:51:47 PM  tests
d----        9/22/2026 2:02:40 PM  Tools
d----        8/30/2026 6:04:04 PM  unraid
-a--- 96     8/30/2026 6:04:02 PM  .dockerignore
-a--- 182    8/16/2026 7:59:10 PM  .env
-a--- 418    8/30/2026 6:08:09 PM  .env.example
-a--- 861    8/29/2026 9:36:25 PM  .gitignore
-a--- 635    8/16/2026 7:38:55 PM  alembic.ini
-a--- 604    8/30/2026 6:04:03 PM  docker-compose.yml
-a--- 788    8/30/2026 6:04:01 PM  docker-entrypoint.sh
-a--- 813    8/30/2026 6:04:01 PM  Dockerfile
-a--- 821    8/30/2026 6:04:00 PM  pyproject.toml
-a--- 21466  8/29/2026 3:28:32 PM  README.md

```

## Relevant source files

```text
D:\YT-Visuals\.dockerignore
D:\YT-Visuals\.env
D:\YT-Visuals\.env.example
D:\YT-Visuals\.gitignore
D:\YT-Visuals\alembic.ini
D:\YT-Visuals\docker-compose.yml
D:\YT-Visuals\docker-entrypoint.sh
D:\YT-Visuals\Dockerfile
D:\YT-Visuals\pyproject.toml
D:\YT-Visuals\README.md
D:\YT-Visuals\.github\workflows\publish-ghcr.yml
D:\YT-Visuals\.pytest_cache\.gitignore
D:\YT-Visuals\.pytest_cache\CACHEDIR.TAG
D:\YT-Visuals\.pytest_cache\README.md
D:\YT-Visuals\.pytest_cache\v\cache\lastfailed
D:\YT-Visuals\.pytest_cache\v\cache\nodeids
D:\YT-Visuals\.venv\pyvenv.cfg
D:\YT-Visuals\.venv\Include\site\python3.11\greenlet\greenlet.h
D:\YT-Visuals\.venv\Lib\site-packages\__editable__.yt_visuals-0.1.0.pth
D:\YT-Visuals\.venv\Lib\site-packages\distutils-precedence.pth
D:\YT-Visuals\.venv\Lib\site-packages\py.py
D:\YT-Visuals\.venv\Lib\site-packages\typing_extensions.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__main__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\command.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\config.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\context.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\context.pyi
D:\YT-Visuals\.venv\Lib\site-packages\alembic\environment.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\migration.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\op.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\op.pyi
D:\YT-Visuals\.venv\Lib\site-packages\alembic\py.typed
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\api.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\render.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\rewriter.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\check_constraints.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\comments.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\constraints.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\schema.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\server_defaults.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\tables.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\types.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\util.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\check_constraints.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\comments.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\constraints.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\schema.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\server_defaults.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\tables.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\types.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\util.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__pycache__\api.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__pycache__\render.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__pycache__\rewriter.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\_autogen.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\base.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\impl.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\mssql.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\mysql.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\oracle.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\postgresql.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\sqlite.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\_autogen.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\base.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\impl.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\mssql.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\mysql.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\oracle.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\postgresql.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\sqlite.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\base.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\batch.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\ops.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\schemaobj.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\toimpl.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\base.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\batch.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\ops.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\schemaobj.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\toimpl.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\environment.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\migration.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\plugins.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__pycache__\environment.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__pycache__\migration.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__pycache__\plugins.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\base.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\revision.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\write_hooks.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__pycache__\base.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__pycache__\revision.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__pycache__\write_hooks.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\pyproject.toml.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\pyproject.toml.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\assertions.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\fixtures.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\requirements.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\schemacompare.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\util.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\warnings.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\plugin\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\plugin\bootstrap.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\plugin\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\plugin\__pycache__\bootstrap.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\_autogen_fixtures.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_comments.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_computed.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_diffs.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_fks.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_identity.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_environment.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_op.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\_autogen_fixtures.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_comments.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_computed.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_diffs.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_fks.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_identity.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_environment.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_op.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\assertions.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\fixtures.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\requirements.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\schemacompare.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\util.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\warnings.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\compat.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\editor.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\exc.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\langhelpers.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\messaging.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\pyfiles.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\sqla_compat.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\compat.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\editor.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\exc.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\langhelpers.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\messaging.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\pyfiles.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\sqla_compat.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\__main__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\command.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\config.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\context.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\environment.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\migration.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\op.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\entry_points.txt
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\INSTALLER
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\METADATA
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\RECORD
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\top_level.txt
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\WHEEL
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\licenses\LICENSE
D:\YT-Visuals\.venv\Lib\site-packages\annotated_types\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\annotated_types\py.typed
D:\YT-Visuals\.venv\Lib\site-packages\annotated_types\test_cases.py
D:\YT-Visuals\.venv\Lib\site-packages\annotated_types\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\annotated_types\__pycache__\test_cases.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\annotated_types-0.8.0.dist-info\INSTALLER
D:\YT-Visuals\.venv\Lib\site-packages\annotated_types-0.8.0.dist-info\METADATA
D:\YT-Visuals\.venv\Lib\site-packages\annotated_types-0.8.0.dist-info\RECORD
[truncated]```

## Key symbols and routes

```text
rg not installed; skip symbol snapshot
```

## Migrations

```text
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\entry_points.txt
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\INSTALLER
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\licenses\LICENSE
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\METADATA
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\RECORD
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\top_level.txt
D:\YT-Visuals\.venv\Lib\site-packages\alembic-1.19.1.dist-info\WHEEL
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__main__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\__main__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\command.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\config.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\context.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\environment.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\migration.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\__pycache__\op.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__pycache__\api.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__pycache__\render.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\__pycache__\rewriter.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\api.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\check_constraints.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\comments.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\constraints.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\schema.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\server_defaults.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\tables.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\types.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\__pycache__\util.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\check_constraints.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\comments.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\constraints.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\schema.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\server_defaults.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\tables.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\types.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\compare\util.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\render.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\autogenerate\rewriter.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\command.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\config.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\context.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\context.pyi
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\_autogen.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\base.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\impl.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\mssql.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\mysql.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\oracle.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\postgresql.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\__pycache__\sqlite.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\_autogen.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\base.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\impl.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\mssql.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\mysql.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\oracle.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\postgresql.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\ddl\sqlite.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\environment.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\migration.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\op.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\op.pyi
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\base.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\batch.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\ops.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\schemaobj.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\__pycache__\toimpl.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\base.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\batch.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\ops.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\schemaobj.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\operations\toimpl.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\py.typed
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__pycache__\environment.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__pycache__\migration.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\__pycache__\plugins.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\environment.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\migration.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\runtime\plugins.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__pycache__\base.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__pycache__\revision.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\__pycache__\write_hooks.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\base.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\revision.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\script\write_hooks.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\async\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\generic\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\multidb\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\pyproject.toml.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject_async\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\alembic.ini.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\pyproject.toml.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\README
D:\YT-Visuals\.venv\Lib\site-packages\alembic\templates\pyproject\script.py.mako
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\assertions.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\fixtures.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\requirements.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\schemacompare.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\util.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\__pycache__\warnings.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\assertions.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\env.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\fixtures.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\plugin\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\plugin\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\plugin\__pycache__\bootstrap.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\plugin\bootstrap.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\requirements.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\schemacompare.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\_autogen_fixtures.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_comments.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_computed.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_diffs.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_fks.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_autogen_identity.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_environment.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\__pycache__\test_op.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\_autogen_fixtures.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_comments.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_computed.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_diffs.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_fks.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_identity.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_environment.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_op.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\util.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\warnings.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__init__.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\__init__.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\compat.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\editor.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\exc.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\langhelpers.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\messaging.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\pyfiles.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\__pycache__\sqla_compat.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\compat.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\editor.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\exc.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\langhelpers.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\messaging.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\pyfiles.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\util\sqla_compat.py
D:\YT-Visuals\.venv\Lib\site-packages\pydantic\__pycache__\_migration.cpython-311.pyc
D:\YT-Visuals\.venv\Lib\site-packages\pydantic\_migration.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\dialects\type_migration_guidelines.txt
D:\YT-Visuals\.venv\Scripts\alembic.exe
D:\YT-Visuals\alembic.ini
D:\YT-Visuals\migrations\__pycache__\env.cpython-311.pyc
D:\YT-Visuals\migrations\env.py
D:\YT-Visuals\migrations\README.md
D:\YT-Visuals\migrations\script.py.mako
D:\YT-Visuals\migrations\versions\__pycache__\0001_initial_catalog.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0002_media_download_history.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0003_local_media_locations.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0004_usage_service_context.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0005_visual_review_workflow.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0006_producer_workspaces.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0007_workspace_organization.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0008_release_metadata.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0009_sfx_catalog.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0010_release_production_memory.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0011_edit_plan_guidance.cpython-311.pyc
D:\YT-Visuals\migrations\versions\__pycache__\0012_story_docum
[truncated]```

## Alembic heads

```text
0013_release_production_artifacts (head)
```

## SQLite schema summary

```text

TABLE alembic_version
CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
)

TABLE asset_licenses
CREATE TABLE asset_licenses (
	id INTEGER NOT NULL, 
	asset_id INTEGER NOT NULL, 
	license_name VARCHAR(255), 
	license_url VARCHAR(2048), 
	attribution_required BOOLEAN DEFAULT '0' NOT NULL, 
	attribution_text TEXT, 
	usage_terms TEXT, 
	commercial_use_allowed BOOLEAN, 
	modifications_allowed BOOLEAN, 
	verified_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_asset_licenses PRIMARY KEY (id), 
	CONSTRAINT fk_asset_licenses_asset_id_media_assets FOREIGN KEY(asset_id) REFERENCES media_assets (id) ON DELETE CASCADE, 
	CONSTRAINT uq_asset_licenses_asset_id UNIQUE (asset_id)
)
FOREIGN KEYS:
(0, 0, 'media_assets', 'asset_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')

TABLE asset_review_annotations
CREATE TABLE asset_review_annotations (
	id INTEGER NOT NULL, 
	asset_id INTEGER NOT NULL, 
	review_id VARCHAR(36) NOT NULL, 
	source_type VARCHAR(40) DEFAULT 'chatgpt_visual_review' NOT NULL, 
	annotations_json JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_asset_review_annotations PRIMARY KEY (id), 
	CONSTRAINT ck_asset_review_annotations_source_type CHECK (source_type = 'chatgpt_visual_review'), 
	CONSTRAINT fk_asset_review_annotations_asset_id_media_assets FOREIGN KEY(asset_id) REFERENCES media_assets (id) ON DELETE CASCADE, 
	CONSTRAINT fk_asset_review_annotations_review_id_visual_reviews FOREIGN KEY(review_id) REFERENCES visual_reviews (review_id) ON DELETE CASCADE, 
	CONSTRAINT uq_asset_review_annotations_asset_review UNIQUE (asset_id, review_id)
)
FOREIGN KEYS:
(0, 0, 'visual_reviews', 'review_id', 'review_id', 'NO ACTION', 'CASCADE', 'NONE')
(1, 0, 'media_assets', 'asset_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')

TABLE asset_tags
CREATE TABLE asset_tags (
	asset_id INTEGER NOT NULL, 
	tag_id INTEGER NOT NULL, 
	tagged_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_asset_tags PRIMARY KEY (asset_id, tag_id), 
	CONSTRAINT fk_asset_tags_asset_id_media_assets FOREIGN KEY(asset_id) REFERENCES media_assets (id) ON DELETE CASCADE, 
	CONSTRAINT fk_asset_tags_tag_id_tags FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
)
FOREIGN KEYS:
(0, 0, 'tags', 'tag_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')
(1, 0, 'media_assets', 'asset_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')

TABLE asset_usages
CREATE TABLE "asset_usages" (
	id INTEGER NOT NULL, 
	asset_id INTEGER NOT NULL, 
	story_id INTEGER, 
	segment_label VARCHAR(255), 
	narration_start_ms INTEGER, 
	narration_end_ms INTEGER, 
	usage_role VARCHAR(100), 
	used_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	notes TEXT, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	project_id INTEGER, 
	usage_reference VARCHAR(255), 
	idempotency_key VARCHAR(255), 
	CONSTRAINT pk_asset_usages PRIMARY KEY (id), 
	CONSTRAINT ck_asset_usages_start_nonnegative CHECK (narration_start_ms IS NULL OR narration_start_ms >= 0), 
	CONSTRAINT ck_asset_usages_end_nonnegative CHECK (narration_end_ms IS NULL OR narration_end_ms >= 0), 
	CONSTRAINT fk_asset_usages_story_id_stories FOREIGN KEY(story_id) REFERENCES stories (id) ON DELETE CASCADE, 
	CONSTRAINT ck_asset_usages_end_after_start CHECK (narration_start_ms IS NULL OR narration_end_ms IS NULL OR narration_end_ms >= narration_start_ms), 
	CONSTRAINT fk_asset_usages_asset_id_media_assets FOREIGN KEY(asset_id) REFERENCES media_assets (id) ON DELETE CASCADE, 
	CONSTRAINT fk_asset_usages_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	CONSTRAINT uq_asset_usages_idempotency_key UNIQUE (idempotency_key)
)
FOREIGN KEYS:
(0, 0, 'projects', 'project_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')
(1, 0, 'media_assets', 'asset_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')
(2, 0, 'stories', 'story_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')

TABLE beat_asset_rejections
CREATE TABLE beat_asset_rejections (
	id INTEGER NOT NULL, 
	workflow_id VARCHAR(36) NOT NULL, 
	beat_id VARCHAR(36) NOT NULL, 
	candidate_id VARCHAR(36) NOT NULL, 
	asset_id INTEGER NOT NULL, 
	asset_sha256 VARCHAR(64) NOT NULL, 
	review_id VARCHAR(36) NOT NULL, 
	rejected_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_beat_asset_rejections PRIMARY KEY (id), 
	CONSTRAINT fk_beat_asset_rejections_workflow_id_visual_workflows FOREIGN KEY(workflow_id) REFERENCES visual_workflows (id) ON DELETE CASCADE, 
	CONSTRAINT fk_beat_asset_rejections_beat_id_visual_beats FOREIGN KEY(beat_id) REFERENCES visual_beats (id) ON DELETE CASCADE, 
	CONSTRAINT fk_beat_asset_rejections_candidate_id_beat_candidates FOREIGN KEY(candidate_id) REFERENCES beat_candidates (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_beat_asset_rejections_asset_id_media_assets FOREIGN KEY(asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_beat_asset_rejections_review_id_visual_reviews FOREIGN KEY(review_id) REFERENCES visual_reviews (review_id) ON DELETE RESTRICT, 
	CONSTRAINT uq_beat_asset_rejections_candidate UNIQUE (workflow_id, beat_id, candidate_id)
)
FOREIGN KEYS:
(0, 0, 'visual_reviews', 'review_id', 'review_id', 'NO ACTION', 'RESTRICT', 'NONE')
(1, 0, 'media_assets', 'asset_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE')
(2, 0, 'beat_candidates', 'candidate_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE')
(3, 0, 'visual_beats', 'beat_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')
(4, 0, 'visual_workflows', 'workflow_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')

TABLE beat_candidates
CREATE TABLE beat_candidates (
	id VARCHAR(36) NOT NULL, 
	package_id VARCHAR(36) NOT NULL, 
	beat_id VARCHAR(36) NOT NULL, 
	asset_id INTEGER NOT NULL, 
	asset_sha256 VARCHAR(64) NOT NULL, 
	status VARCHAR(24) DEFAULT 'proposed' NOT NULL, 
	retrieval_json JSON NOT NULL, 
	preview_json JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_beat_candidates PRIMARY KEY (id), 
	CONSTRAINT ck_beat_candidates_status CHECK (status IN ('proposed', 'rejected', 'accepted', 'locked_carried')), 
	CONSTRAINT fk_beat_candidates_package_id_candidate_packages FOREIGN KEY(package_id) REFERENCES candidate_packages (id) ON DELETE CASCADE, 
	CONSTRAINT fk_beat_candidates_beat_id_visual_beats FOREIGN KEY(beat_id) REFERENCES visual_beats (id) ON DELETE CASCADE, 
	CONSTRAINT fk_beat_candidates_asset_id_media_assets FOREIGN KEY(asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT, 
	CONSTRAINT uq_beat_candidates_package_beat UNIQUE (package_id, beat_id)
)
FOREIGN KEYS:
(0, 0, 'media_assets', 'asset_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE')
(1, 0, 'visual_beats', 'beat_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')
(2, 0, 'candidate_packages', 'package_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')

TABLE beat_selections
CREATE TABLE beat_selections (
	id INTEGER NOT NULL, 
	workflow_id VARCHAR(36) NOT NULL, 
	beat_id VARCHAR(36) NOT NULL, 
	candidate_id VARCHAR(36) NOT NULL, 
	asset_id INTEGER NOT NULL, 
	asset_sha256 VARCHAR(64) NOT NULL, 
	review_id VARCHAR(36) NOT NULL, 
	alignment_score INTEGER NOT NULL, 
	lock_compatibility_sha256 VARCHAR(64) NOT NULL, 
	status VARCHAR(24) DEFAULT 'locked' NOT NULL, 
	blocked_reason VARCHAR(64), 
	locked_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_beat_selections PRIMARY KEY (id), 
	CONSTRAINT ck_beat_selections_score_acceptance CHECK (alignment_score BETWEEN 90 AND 100), 
	CONSTRAINT ck_beat_selections_status CHECK (status IN ('locked', 'blocked_missing')), 
	CONSTRAINT fk_beat_selections_workflow_id_visual_workflows FOREIGN KEY(workflow_id) REFERENCES visual_workflows (id) ON DELETE CASCADE, 
	CONSTRAINT fk_beat_selections_beat_id_visual_beats FOREIGN KEY(beat_id) REFERENCES visual_beats (id) ON DELETE CASCADE, 
	CONSTRAINT fk_beat_selections_candidate_id_beat_candidates FOREIGN KEY(candidate_id) REFERENCES beat_candidates (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_beat_selections_asset_id_media_assets FOREIGN KEY(asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_beat_selections_review_id_visual_reviews FOREIGN KEY(review_id) REFERENCES visual_reviews (review_id) ON DELETE RESTRICT, 
	CONSTRAINT uq_beat_selections_workflow_beat UNIQUE (workflow_id, beat_id)
)
FOREIGN KEYS:
(0, 0, 'visual_reviews', 'review_id', 'review_id', 'NO ACTION', 'RESTRICT', 'NONE')
(1, 0, 'media_assets', 'asset_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE')
(2, 0, 'beat_candidates', 'candidate_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE')
(3, 0, 'visual_beats', 'beat_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')
(4, 0, 'visual_workflows', 'workflow_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')

TABLE candidate_packages
CREATE TABLE candidate_packages (
	id VARCHAR(36) NOT NULL, 
	workflow_id VARCHAR(36) NOT NULL, 
	request_revision_id VARCHAR(36) NOT NULL, 
	iteration INTEGER NOT NULL, 
	status VARCHAR(24) DEFAULT 'building' NOT NULL, 
	candidate_report_path VARCHAR(1024), 
	candidate_report_sha256 VARCHAR(64), 
	storyboard_path VARCHAR(1024), 
	storyboard_sha256 VARCHAR(64), 
	review_template_path VARCHAR(1024), 
	review_template_sha256 VARCHAR(64), 
	review_id VARCHAR(36) NOT NULL, 
	generated_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_candidate_packages PRIMARY KEY (id), 
	CONSTRAINT ck_candidate_packages_iteration_positive CHECK (iteration > 0), 
	CONSTRAINT ck_candidate_packages_status CHECK (status IN ('building', 'awaiting_review', 'reviewed', 'generation_failed')), 
	CONSTRAINT fk_candidate_packages_workflow_id_visual_workflows FOREIGN KEY(workflow_id) REFERENCES visual_workflows (id) ON DELETE CASCADE, 
	CONSTRAINT fk_candidate_packages_request_revision_id_visual_request_revisions FOREIGN KEY(request_revision_id) REFERENCES visual_request_revisions (id) ON DELETE RESTRICT, 
	CONSTRAINT uq_candidate_packages_workflow_iteration UNIQUE (workflow_id, iteration), 
	CONSTRAINT uq_candidate_packages_review_id UNIQUE (review_id)
)
FOREIGN KEYS:
(0, 0, 'visual_request_revisions', 'request_revision_id', 'id', 'NO ACTION', 'RESTRICT', 'NONE')
(1, 0, 'visual_workflows', 'workflow_id', 'id', 'NO ACTION', 'CASCADE', 'NONE')

TABLE media_assets
CREATE TABLE "media_assets" (
	id INTEGER NOT NULL, 
	relative_path VARCHAR(1024) NOT NULL, 
	media_type VARCHAR(16) NOT NULL, 
	status VARCHAR(16) DEFAULT 'active' NOT NULL, 
	title VARCHAR(255), 
	description TEXT, 
	mime_type VARCHAR(127), 
	file_size_bytes INTEGER, 
	sha256 VARCHAR(64), 
	width INTEGER, 
	height INTEGER, 
	duration_ms INTEGER, 
	file_modified_at DATETIME, 
	captured_at DATETIME, 
	imported_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	last_verified_at DATETIME, 
	usage_count INTEGER DEFAULT '0' NOT NULL, 
	last_used_at DATETIME, 
	technical_metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	sfx_kind VARCHAR(16), 
	CONSTRAINT pk_media_assets PRIMARY KEY (id), 
	CONSTRAINT ck_media_assets_duration_nonnegative CHECK (duration_ms IS NULL OR duration_ms >= 0), 
	CONSTRAINT ck_media_assets_height_positive CHECK (height IS NULL OR height > 0), 
	CONSTRAINT ck_media_assets_sha256_length CHECK (sha256 IS NULL OR length(sha256) = 64), 
	CONSTRAINT ck_media_assets_file_size_nonnegative CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0), 
	CONSTRAINT ck_media_assets_usage_count_nonnegative CHECK (usage_count >= 0), 
	CONSTRAINT ck_media_assets_relative_path_not_empty CHECK (length(trim(relative_path)) > 0), 
	CONSTRAINT ck_media_assets_status CHECK (status IN ('active', 'archived', 'missing')), 
	CONSTRAINT uq_media_assets_sha256 UNIQUE (sha256), 
	CONSTRAINT ck_media_assets_sha256_lower_hex CHECK (sha256 IS NULL OR sha256 NOT GLOB '*[^0-9a-f]*'), 
	CONSTRAINT ck_media_assets_relative_path_not_backslash_absolute CHECK (substr(relative_path, 1, 1) != char(92)), 
	CONSTRAINT ck_media_assets_width_positive CHECK (width IS NULL OR width > 0), 
	CONSTRAINT ck_media_assets_relative_path_not_posix_absolute CHECK (relative_path NOT LIKE '/%'), 
	CONSTRAINT uq_media_assets_relative_path UNIQUE (relative_path), 
	CONSTRAINT ck_media_assets_relative_path_not_drive_absolute CHECK (relative_path NOT GLOB '[A-Za-z]:*'), 
	CONSTRAINT ck_media_assets_media_type CHECK (media_type IN ('image', 'video', 'audio')), 
	CONSTRAINT ck_media_assets_sfx_kind CHECK (sfx_kind IS NULL OR sfx_kind IN ('one_shot', 'ambient'))
)

TABLE media_downloads
CREATE TABLE "media_downloads" (
	id INTEGER NOT NULL, 
	provider VARCHAR(100) NOT NULL, 
	provider_asset_id VARCHAR(255) NOT NULL, 
	media_type VARCHAR(16) NOT NULL, 
	source_url VARCHAR(2048), 
	download_url VARCHAR(4096), 
	attempted_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	completed_at DATETIME, 
	status VARCHAR(16) DEFAULT 'started' NOT NULL, 
	media_asset_id INTEGER, 
	relative_path VARCHAR(1024), 
	sha256 VARCHAR(64), 
	downloaded_bytes INTEGER, 
	http_status_code INTEGER, 
	content_type VARCHAR(255), 
	error_category VARCHAR(100), 
	error_message TEXT, 
	provider_metadata JSON, 
	request_metadata JSON, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	updated_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	CONSTRAINT pk_media_downloads PRIMARY KEY (id), 
	CONSTRAINT ck_media_downloads_path_not_backslash_absolute CHECK (relative_path IS NULL OR substr(relative_path, 1, 1) != char(92)), 
	CONSTRAINT ck_media_downloads_sha256_length CHECK (sha256 IS NULL OR length(sha256) = 64), 
	CONSTRAINT ck_media_downloads_http_status_range CHECK (http_status_code IS NULL OR http_status_code BETWEEN 100 AND 599), 
	CONSTRAINT ck_media_downloads_path_not_posix_absolute CHECK (relative_path IS NULL OR relative_path NOT LIKE '/%'), 
	CONSTRAINT fk_media_downloads_media_asset_id_media_assets FOREIGN KEY(media_asset_id) REFERENCES media_assets (id) ON DELETE SET NULL, 
	CONSTRAINT ck_media_downloads_path_not_drive_absolute CHECK (relative_path IS NULL OR relative_path NOT GLOB '[A-Za-z]:*'), 
	CONSTRAINT ck_media_downloads_provider_asset_id_not_empty CHECK (length(trim(provider_asset_id)) > 0), 
	CONSTRAINT ck_media_downloads_sha256_lower_hex CHECK (sha256 IS NULL OR sha256 NOT GLOB '*[^0-9a-f]*'), 
	CONSTRAINT ck_media_downloads_completed_after_attempted CHECK (completed_at IS NULL OR completed_at >= attempted_at), 
	CONSTRAINT ck_media_downloads_status CHECK (status IN ('started', 'success', 'failed', 'duplicate', 'reused')), 
	CONSTRAINT ck_media_downloads_bytes_nonnegative CHECK (downloaded_bytes IS NULL OR downloaded_bytes >= 0), 
	CONSTRAINT ck_media_downloads_provider_not_empty CHECK (length(trim(provider)) > 0), 
	CONSTRAINT ck_media_downloads_media_type CHECK (media_type IN ('image', 'video', 'audio'))
)
FOREIGN KEYS:
(0, 0, 'media_assets', 'media_asset_id', 'id', 'NO ACTION', 'SET NULL', 'NONE')

TABLE media_locations
CREATE TABLE media_locations (
	id INTEGER NOT NULL, 
	media_asset_id INTEGER NOT NULL, 
	relative_path VARCHAR(1024) COLLATE "NOCASE" NOT NULL, 
	status VARCHAR(16) DEFAULT 'available' NOT NULL, 
	provenance_type VARCHAR(32) NOT NULL, 
	file_size_bytes INTEGER, 
	file_modified_ns INTEGER, 
	file_modifi
[truncated]```

## Focused tests inventory

```text
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_comments.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_computed.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_diffs.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_fks.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_autogen_identity.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_environment.py
D:\YT-Visuals\.venv\Lib\site-packages\alembic\testing\suite\test_op.py
D:\YT-Visuals\.venv\Lib\site-packages\annotated_types\test_cases.py
D:\YT-Visuals\.venv\Lib\site-packages\certifi\tests\test_certify.py
D:\YT-Visuals\.venv\Lib\site-packages\click\testing.py
D:\YT-Visuals\.venv\Lib\site-packages\flask\testing.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_contextvars.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_cpp.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_extension_interface.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_gc.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_generator_nested.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_generator.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_greenlet_trash.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_greenlet.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_interpreter_shutdown.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_leaks.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_stack_saved.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_throw.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_tracing.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_version.py
D:\YT-Visuals\.venv\Lib\site-packages\greenlet\tests\test_weakref.py
D:\YT-Visuals\.venv\Lib\site-packages\jinja2\tests.py
D:\YT-Visuals\.venv\Lib\site-packages\pip\_vendor\pyparsing\testing.py
D:\YT-Visuals\.venv\Lib\site-packages\pip\_vendor\webencodings\tests.py
D:\YT-Visuals\.venv\Lib\site-packages\pkg_resources\_vendor\pyparsing\testing.py
D:\YT-Visuals\.venv\Lib\site-packages\pygments\lexers\testing.py
D:\YT-Visuals\.venv\Lib\site-packages\reportlab\graphics\testdrawings.py
D:\YT-Visuals\.venv\Lib\site-packages\reportlab\graphics\testshapes.py
D:\YT-Visuals\.venv\Lib\site-packages\reportlab\graphics\barcode\test.py
D:\YT-Visuals\.venv\Lib\site-packages\reportlab\lib\testutils.py
D:\YT-Visuals\.venv\Lib\site-packages\setuptools\command\test.py
D:\YT-Visuals\.venv\Lib\site-packages\setuptools\_vendor\pyparsing\testing.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_cte.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_ddl.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_deprecations.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_dialect.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_insert.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_reflection.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_results.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_rowcount.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_select.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_sequence.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_types.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_unicode_ddl.py
D:\YT-Visuals\.venv\Lib\site-packages\sqlalchemy\testing\suite\test_update_delete.py
D:\YT-Visuals\.venv\Lib\site-packages\werkzeug\test.py
D:\YT-Visuals\.venv\Lib\site-packages\werkzeug\testapp.py
D:\YT-Visuals\.venv\Lib\site-packages\win32ctypes\tests\test_backends.py
D:\YT-Visuals\.venv\Lib\site-packages\win32ctypes\tests\test_win32api.py
D:\YT-Visuals\.venv\Lib\site-packages\win32ctypes\tests\test_win32cred.py
D:\YT-Visuals\tests\test_acquisition.py
D:\YT-Visuals\tests\test_credentials.py
D:\YT-Visuals\tests\test_database.py
D:\YT-Visuals\tests\test_deployment_foundation.py
D:\YT-Visuals\tests\test_doctor.py
D:\YT-Visuals\tests\test_edit_plan_contract.py
D:\YT-Visuals\tests\test_library.py
D:\YT-Visuals\tests\test_models.py
D:\YT-Visuals\tests\test_pexels_provider.py
D:\YT-Visuals\tests\test_phase5a_workflow.py
D:\YT-Visuals\tests\test_producer_web.py
D:\YT-Visuals\tests\test_producer_workflow.py
D:\YT-Visuals\tests\test_provider_cli.py
D:\YT-Visuals\tests\test_services.py
D:\YT-Visuals\tests\test_unraid_migration.py
D:\YT-Visuals\tests\test_visual_plan_contract.py
D:\YT-Visuals\tests\test_visual_workflow.py
D:\YT-Visuals\tests\test_web_startup.py
D:\YT-Visuals\tests\test_workflow_contracts.py
```

## Storage/path assumptions

```text
rg not installed; skip path snapshot
```
