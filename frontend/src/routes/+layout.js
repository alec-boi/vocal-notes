const sidebarModules = import.meta.glob('./**/*Sidebar.svelte'); 

/** @type {import('./$types').LayoutLoad} */
export async function load({ route }) {
    const routeId = route.id;

    if (routeId !== null) {
        const dir = routeId.split('/').filter(Boolean).join('/');
        const sidebarKey = `./${dir}/Sidebar.svelte`.replace('.///', './');

        const loadModule = sidebarModules[sidebarKey];
        if (loadModule) {
            const componentModule = await loadModule();
            return {
                sidebarComponent: componentModule.default
            };
        }
    }

    return {
        sidebarComponent: null
    };
}