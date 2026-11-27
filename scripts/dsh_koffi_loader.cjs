/**
 * CommonJS preload for the bundled DSH runtime.
 *
 * Node's ESM resolve hooks and NODE_PATH do not cover the runtime's
 * `createRequire('koffi')` path. This preload patches Module._resolveFilename
 * so both the bare `koffi` specifier and the absolute platform binding path are
 * redirected to the real sidecar files downloaded by
 * `scripts/prepare_dsh_runtime.py`. It also redirects `node-pty` and its
 * conpty/pty native binaries, because the same single-file packaging leaves
 * the bundled `pwsh` tool without `prebuilds/win32-x64/conpty.node`.
 */
'use strict'

const Module = require('node:module')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const entry = process.env.DSH_KOFFI_ENTRY
const platformBinary = process.env.DSH_KOFFI_PLATFORM
const ptyEntry = process.env.DSH_NODE_PTY_ENTRY
const ptyPrebuild = process.env.DSH_NODE_PTY_PREBUILD_DIR
const ptyBinaries = new Set(['conpty.node', 'conpty_console_list.node', 'pty.node'])

function log(message) {
  if (!process.env.DSH_LOADER_LOG) return
  try {
    require('node:fs').appendFileSync(
      process.env.DSH_LOADER_LOG,
      `${process.pid} ${message}\n`,
    )
  } catch {
    // Diagnostics must never block the runtime.
  }
}

function ptyBinaryFor(request) {
  if (!ptyPrebuild || typeof request !== 'string') return null
  const basename = path.basename(request)
  if (!ptyBinaries.has(basename)) return null
  if (!request.includes('node-pty') && !request.includes('prebuilds')) return null
  return path.join(ptyPrebuild, basename)
}

if (entry || ptyEntry) {
  if (typeof Module.registerHooks === 'function') {
    Module.registerHooks({
      resolve(specifier, context, nextResolve) {
        if (specifier === 'node-pty' && ptyEntry) {
          log(`require-hook node-pty -> ${ptyEntry}`)
          return { url: pathToFileURL(ptyEntry).href, shortCircuit: true }
        }
        if (specifier === 'koffi' && entry) {
          log(`require-hook koffi -> ${entry}`)
          return { url: pathToFileURL(entry).href, shortCircuit: true }
        }
        return nextResolve(specifier, context)
      },
    })
  }

  const originalLoad = Module._load
  Module._load = function load(request, parent, isMain) {
    const loaded = originalLoad.call(this, request, parent, isMain)
    if (request === 'node-pty' && loaded && !loaded.__zyourroadPatched) {
      log('load node-pty (force useConptyDll=false)')
      const originalSpawn = loaded.spawn
      if (typeof originalSpawn === 'function') {
        loaded.spawn = (file, args, options = {}) => {
          log(
            `spawn ${file} args=${JSON.stringify(args)} cwd=${options.cwd} `
            + `rows=${options.rows} cols=${options.cols} keys=${Object.keys(options)}`,
          )
          return originalSpawn(file, args, { ...options, useConptyDll: false })
        }
      }
      Object.defineProperty(loaded, '__zyourroadPatched', { value: true })
    }
    return loaded
  }

  const originalResolveFilename = Module._resolveFilename
  Module._resolveFilename = function resolveFilename(
    request,
    parent,
    isMain,
    options,
  ) {
    if (
      typeof request === 'string'
      && (request.includes('koffi') || request.includes('node-pty') || request.includes('conpty'))
    ) {
      log(`resolve ${request}`)
    }
    if (request === 'koffi') return entry
    if (request === 'node-pty' && ptyEntry) return ptyEntry
    if (
      platformBinary
      && typeof request === 'string'
      && request.includes('@koromix')
      && request.endsWith('koffi.node')
    ) {
      return platformBinary
    }
    const ptyBinary = ptyBinaryFor(request)
    if (ptyBinary) return ptyBinary
    if (
      ptyEntry
      && typeof request === 'string'
      && request.includes('node-pty')
      && (
        request.endsWith('conoutSocketWorker.js')
        || request.includes('conpty_console_list_agent')
      )
    ) {
      const match = request.match(/node-pty[\\/](.*)$/)
      let relative = match?.[1]?.replace(/^lib[\\/]/, '')
      if (relative) {
        const redirected = path.join(path.dirname(ptyEntry), relative)
        log(`redirect worker ${request} -> ${redirected}`)
        return redirected
      }
    }
    return originalResolveFilename.call(this, request, parent, isMain, options)
  }

  // The bundled runtime may hand a virtual snapshot path straight to
  // process.dlopen; redirect any koffi native load to the real sidecar.
  if (platformBinary || ptyPrebuild) {
    const originalDlopen = process.dlopen
    process.dlopen = function dlopen(module, filename, flags) {
      if (typeof filename === 'string' && filename.includes('conpty')) {
        log(`dlopen ${filename}`)
      }
      if (
        platformBinary
        && typeof filename === 'string'
        && (filename.includes('@koromix') || filename.endsWith('koffi.node'))
      ) {
        return originalDlopen.call(this, module, platformBinary, flags)
      }
      const ptyBinary = ptyBinaryFor(filename)
      if (ptyBinary) {
        return originalDlopen.call(this, module, ptyBinary, flags)
      }
      return originalDlopen.call(this, module, filename, flags)
    }
  }
}
