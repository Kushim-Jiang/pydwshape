NOTICE

pydwshape bundles the following third-party binary (Microsoft-signed,
unmodified), redistributed under its original license terms:

  DWriteCore.dll
    Version      : 2.1.1.2605
    Source       : Microsoft Windows App SDK, NuGet package
                   "Microsoft.WindowsAppSDK.DWrite" (2.1.0)
    Copyright    : (c) Microsoft Corporation
    License      : Microsoft Windows App SDK license terms
    Redistribution allowed as part of applications built with the Windows
                   App SDK; see the license terms shipped with that package.

This component is used at runtime to perform shaping; it is not part of this
project's own MIT-licensed source code.


pydwshape also bundles a standalone build of the **Wine DWrite port**
(``winedwrite.dll`` / ``libwinedwrite.so`` / ``libwinedwrite.dylib``):
  winedwrite
    Source       : Wine dlls/dwrite (https://github.com/wine-mirror/wine),
                   ported standalone in this repo at tools/wine_dwrite
    Copyright    : Wine authors (see the file headers)
    License      : GNU Lesser General Public License v2.1 or later (LGPL-2.1-or-later)
This component provides the cross-platform ``backend='winedwrite'`` engine. It
is a separate dynamically-linked LGPL component; this package's own source
remains MIT-licensed.
