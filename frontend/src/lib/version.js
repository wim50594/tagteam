/**
 * App version, sourced from the backend at runtime.
 *
 * The backend's /api/health endpoint reports the version it was built
 * with (APP_VERSION, set from the release's git tag - see
 * .github/workflows/release.yml and backend/Dockerfile). Since backend
 * and frontend are always released together, this single value is the
 * source of truth for the whole app - no hardcoded version strings in
 * the frontend.
 *
 * Falls back to VITE_APP_VERSION (baked in at frontend build time) if the
 * backend can't be reached yet, and finally to "dev".
 */

import { useEffect, useState } from 'react'

import { api } from './api'

const FALLBACK_VERSION = import.meta.env.VITE_APP_VERSION || 'dev'

let cachedVersion = null
let inFlight = null

async function fetchVersion() {
    if (cachedVersion) return cachedVersion
    if (!inFlight) {
        inFlight = api.get('/api/health')
            .then((data) => {
                cachedVersion = data?.version || FALLBACK_VERSION
                return cachedVersion
            })
            .catch(() => {
                cachedVersion = FALLBACK_VERSION
                return cachedVersion
            })
    }
    return inFlight
}

/** Returns the app version string, e.g. "1.4.2" or "dev". */
export function useVersion() {
    const [version, setVersion] = useState(cachedVersion || FALLBACK_VERSION)

    useEffect(() => {
        let active = true
        fetchVersion().then((v) => { if (active) setVersion(v) })
        return () => { active = false }
    }, [])

    return version
}

/** Formats a raw version string as a short badge label, e.g. "v1.4.2". */
export function formatVersionBadge(version) {
    if (!version || version === 'dev') return 'dev'
    return version.startsWith('v') ? version : `v${version}`
}