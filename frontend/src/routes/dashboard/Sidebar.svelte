<script>
    import { onMount } from "svelte";
    import { supabase } from "$lib/subabaseClient";
    import { env } from "$env/dynamic/public";
    import Icon from "@iconify/svelte";

    import {
        history, 
        selectedId, 
        selectAnalysis,
        addAnalysis,
    } from "$lib/analysisStore";

    let isLoading = true;

    let historyItems;
    history.subscribe((value) => {
        historyItems = value;
    });

    let currentId;
    selectedId.subscribe((value) => {
        currentId = value;
    });

    onMount(async () => {
        await loadRecent();
    });

    async function loadRecent() {
        try {
            const {
                data: { session },
            } = await supabase.auth.getSession();

            if (!session) {
                console.log("No session found");
                isLoading = false;
                return;
            }

            const timestamp = new Date().getTime();
            const apiUrl = env.PUBLIC_API_URL.replace(/\/+$/, "") || "";
            const response = await fetch(
                `${apiUrl}/audio/sidebar_recent?limit=5&t=${timestamp}`,
                {
                    headers: {
                        Authorization: `Bearer ${session.access_token}`,
                        "Content-Type": "application/json",
                    },
                    cache: "no-store",
                },
            );

            if (response.ok) {
                const data = await response.json();
                console.log("Recent data received:", data);

                if (data.recent_items && data.recent_items.length > 0) {
                    // Map the API data structure to the store's expected structure
                    const mappedItems = data.recent_items.map((item) => ({
                        id: item.id,
                        title: `${item.title} (${item.artist})`,
                        vocalsUrl: null, // Will be fetched on click
                        notes: null, // Will be fetched on click
                        artist: item.artist,
                        date: item.date,
                        has_data: item.has_data,
                    }));

                    // Directly set the history store
                    history.set(mappedItems);

                    // --- AUTOMATIC SELECTION REMOVED ---
                    // The dashboard will now remain in the search state until an item is clicked.

                } else {
                    history.set([]);
                }
            } else {
                console.error(
                    "Failed to fetch recent:",
                    response.status,
                    response.statusText,
                );
                history.set([]);
            }
        } catch (error) {
            console.error("Failed to load recent:", error);
            history.set([]);
        } finally {
            isLoading = false;
        }
    }

    function formatDate(dateString) {
        if (!dateString) return "";
        const date = new Date(dateString);
        return date.toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
        });
    }

    async function openAnalysis(item) {
        if (!item.has_data || item.id === "error") return;

        const existingFullAnalysis = historyItems.find(
            (a) => a.id === item.id && a.vocalsUrl !== null,
        );

        if (existingFullAnalysis) {
            selectAnalysis(item.id);
            console.log(
                "Loaded analysis from store cache:",
                existingFullAnalysis.title,
            );
            return;
        }

        try {
            const {
                data: { session },
            } = await supabase.auth.getSession();
            if (!session) return;

            const apiUrl = env.PUBLIC_API_URL.replace(/\/+$/, "") || "";
            const res = await fetch(`${apiUrl}/audio/saved_result/${item.id}`, {
                headers: {
                    Authorization: `Bearer ${session.access_token}`,
                },
            });

            if (!res.ok) {
                throw new Error(`Failed to load analysis: ${res.statusText}`);
            }

            const data = await res.json();

            let returnedUrl = data.vocals_url || null;
            let finalUrl = null;

            if (returnedUrl) {
                finalUrl = /^https?:\/\//.test(returnedUrl)
                    ? returnedUrl
                    : `${apiUrl}${returnedUrl.startsWith("/") ? "" : "/"}${returnedUrl}`;
            }

            const fullAnalysis = {
                id: item.id,
                title: data.video_title || item.title,
                vocalsUrl: finalUrl,
                notes: data.notes || [],
                artist: item.artist,
                date: item.date,
                has_data: item.has_data,
            };

            history.update((h) => {
                const index = h.findIndex((a) => a.id === item.id);
                if (index !== -1) {
                    h[index] = { ...h[index], ...fullAnalysis };
                } else {
                    h.push(fullAnalysis);
                }
                return h;
            });

            selectAnalysis(item.id);

            console.log(
                "Loaded analysis from API and updated store:",
                fullAnalysis.title,
            );
        } catch (error) {
            console.error("Error opening analysis:", error);
        }
    }
</script>

<div class="py-4 text-gray-800 h-full w-full p-4">
    <h1 class="text-xl font-bold mb-3 text-gray-400">Recent Analyses</h1>
    <div class="recent-activity flex flex-col space-y-3">
        {#if isLoading}
            {#each Array(5) as _, i}
                <div
                    class="w-full flex-1 py-2 animate-pulse rounded-lg bg-gray-50 p-2"
                >
                    <div class="h-5 bg-gray-200 rounded w-3/4 mb-1"></div>
                    <div class="h-4 bg-gray-100 rounded w-1/2"></div>
                </div>
            {/each}
        {:else if historyItems && historyItems.length > 0}
            {#each historyItems as item (item.id)}
                <button
                    class="w-full flex flex-col py-2 px-2 rounded-lg text-left"
                    on:click={() => openAnalysis(item)}
                    disabled={!item.has_data || item.id === "error"}
                >
                    <div class="flex justify-between items-center">
                        <div class="flex-1 min-w-0">
                            <h3
                                class="text-base text-gray-900 truncate font-semibold"
                                title={item.title}
                            >
                                {item.title}
                            </h3>
                            {#if item.artist}
                                <span
                                    class="text-xs text-fuchsia-500 truncate"
                                    title={item.artist}
                                >
                                    {item.artist}
                                </span>
                            {/if}
                        </div>
                        {#if item.date}
                            <span class="text-xs text-gray-400 ml-2 shrink-0">
                                {formatDate(item.date)}
                            </span>
                        {/if}
                    </div>
                </button>
            {/each}
        {:else}
            <div class="text-center py-6 text-gray-500 text-sm">
                <Icon
                    icon="material-symbols:mic-none"
                    class="w-8 h-8 mx-auto mb-2 text-fuchsia-300"
                />
                <p>No analysis history found. Start by processing a video!</p>
            </div>
        {/if}
    </div>
</div>