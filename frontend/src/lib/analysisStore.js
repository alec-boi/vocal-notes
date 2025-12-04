import { writable, derived } from 'svelte/store';

export const history = writable([]);
export const selectedId = writable(null);

export const currentAnalysis = derived(
    [history, selectedId],
    ([$history, $selectedId]) => {
        const selected = $history.find(a => a.id === $selectedId);
        return selected || null;
    }
);

/**
 * Function to call when a new analysis successfully completes.
 * @param {object} newAnalysis - The full analysis data: { title, vocalsUrl, notes }
 */
export function addAnalysis(newAnalysisData) {
    const newAnalysis = {
        id: crypto.randomUUID(),
        ...newAnalysisData,
        timestamp: Date.now()
    };
    
    history.update(h => [newAnalysis, ...h]);
    
    selectedId.set(newAnalysis.id);
}

/**
 * Function to call when a user clicks an item in the sidebar.
 * @param {string} id - The ID of the analysis the user wants to view.
 */
export function selectAnalysis(id) {
    selectedId.set(id);
}