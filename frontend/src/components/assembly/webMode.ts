// The public web build (assembly.html, built with VITE_ASSEMBLY_WEB=1) has no
// hand and no backend: it shows the external edition read-only and keeps
// progress in the browser.
export const WEB_GUIDE = import.meta.env.VITE_ASSEMBLY_WEB === '1'
