<script>
    import { supabase } from "$lib/subabaseClient";
    import { getContext, onMount } from "svelte";
    import Icon from "@iconify/svelte";

    let user = null;
    let loading = true;
    let authToken = null;

    onMount(async () => {
        const { data: sessionData } = await supabase.auth.getSession();
        const session = sessionData.session;
        user = session?.user;

        if (!user) {
            window.location.href = "/login";
            return;
        }

        authToken = session.access_token;
        loading = false;
    });

    async function logout() {
        await supabase.auth.signOut();
        window.location.href = "/login";
    }

    // reactive searchbar

    let youtubeLinkOrQuery = "";
    let isUrl = false;
    let searchResults = [];
    let videoPreview = null;
    let isSearching = false;

    const youtubeRegex =
        /(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})(?:\S+)?/i;
    const apiUrl = import.meta.env.VITE_API_URL;

    let searchDebounceTimeout;

    $: {
        if (loading || !authToken) "";

        const match = youtubeLinkOrQuery.match(youtubeRegex);
        const isUrlMatch = !!match;

        if (isUrlMatch) {
            isUrl = true;
            searchResults = [];
            fetchVideoDetails(match[1]);
        } else {
            isUrl = false;
            videoPreview = null;

            clearTimeout(searchDebounceTimeout);
            if (youtubeLinkOrQuery.length > 3) {
                isSearching = true;
                searchDebounceTimeout = setTimeout(() => {
                    searchYouTube(youtubeLinkOrQuery);
                }, 500);
            } else {
                searchResults = [];
                isSearching = false;
            }
        }
    }

    async function fetchVideoDetails(videoId) {
        if (!authToken) {
            console.error("Token missing for fetchVideoDetails.");
            return;
        }

        try {
            isSearching = true;
            const res = await fetch(
                `${apiUrl}/youtube/details?video_id=${videoId}`,
                {
                    headers: { Authorization: `Bearer ${authToken}` },
                },
            );

            if (!res.ok) {
                videoPreview = null;
                // Log the exact status and error message from FastAPI if available
                const errorBody = await res.json();
                console.error(`API Error ${res.status}:`, errorBody);
                throw new Error(
                    errorBody.detail || "Could not fetch video details.",
                );
            }

            videoPreview = await res.json();
        } catch (error) {
            console.error(error);
        } finally {
            isSearching = false;
        }
    }

    async function searchYouTube(query) {
        if (!authToken || query.length < 3) {
            console.error("Token missing for searchYouTube.");
            return;
        }

        try {
            const res = await fetch(`${apiUrl}/youtube/search?query=${query}`, {
                headers: { Authorization: `Bearer ${authToken}` },
            });

            if (!res.ok) {
                searchResults = [];
                // Log the exact status and error message from FastAPI if available
                const errorBody = await res.json();
                console.error(`API Error ${res.status}:`, errorBody);
                throw new Error(
                    errorBody.detail || "Could not perform search.",
                );
            }

            const data = await res.json();
            searchResults = data.results;
        } catch (error) {
            console.error(error);
        } finally {
            isSearching = false;
        }
    }

    function selectSearchResult(video) {
        youtubeLinkOrQuery = `https://www.youtube.com/watch?v=${video.id}`;
        searchResults = [];
    }

    //API logic
    let analysisRunning = false;
    let analysisError = null;
    let lastVideoPreview = videoPreview;

    async function startAnalysis(e) {
        e.preventDefault();
        analysisError = null;
        analysisRunning = true;
        videoPreview = null;

        if (loading || !authToken) {
            analysisError = "Authentication not ready. Please wait.";
            analysisRunning = false;
            return;
        }

        let urlToSend;
        if (videoPreview) {
            urlToSend = `https://www.youtube.com/watch?v=${videoPreview.id}`;
        } else if (youtubeLinkOrQuery) {
            urlToSend = youtubeLinkOrQuery;
        } else {
            console.log("No URL provided");
            analysisRunning = false;
            return;
        }

        try {
            isSearching = true;
            const res = await fetch(`${apiUrl}/audio/process`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${authToken}`,
                    apikey: import.meta.env.VITE_SUPABASE_ANON_KEY,
                },
                body: JSON.stringify({ url: urlToSend }),
            });

            if (!res.ok) {
                const errorBody = await res.json();
                analysisError = errorBody.detail || "Unknown API error.";
                throw new Error(analysisError);
            }

            const data = await res.json();
            taskId = data.task_id;
            progress = "downloading";

            if (eventSource) eventSource.close();

            eventSource = new EventSource(`${apiUrl}/audio/progress/${taskId}`);

            eventSource.onmessage = (event) => {
                progress = event.data;

                if (progress === "done") {
                    eventSource.close();
                    analysisRunning = false;
                }
            };

            eventSource.onerror = () => {
                console.error("SSE connection lost");
                eventSource.close();
                analysisRunning = false;
            };
        } catch (error) {
            analysisError =
                analysisError || "Could not connect to the API server.";
            console.error(error);
            analysisRunning = false;
        } finally {
            isSearching = false;
        }
    }

    let taskId = null;
    let progress = null;
    let eventSource = null;

    const progressSteps = ["downloading", "separating", "finalizing", "done"];

    function progressPercentage(step) {
        const index = progressSteps.indexOf(step);
        if (index === -1) return 0;
        return Math.round((index / (progressSteps.length - 1)) * 100);
    }
</script>

<div class="flex flex-col flex-grow gap-6">
    <h1 class="text-center text-6xl text-capitalize text-fuchsia-400 font-bold">
        Paste Your Link
    </h1>

    {#if loading}
        <div class="flex items-center justify-center p-8">
            <Icon
                icon="mdi:loading"
                class="animate-spin w-10 h-10 text-fuchsia-400"
            />
            <span class="ml-3 text-lg text-gray-600"
                >Loading authentication...</span
            >
        </div>
    {:else}
        <form
            on:submit={startAnalysis}
            class="flex items-start w-1/2 max-w-3xl mx-auto space-x-2"
        >
            <label for="simple-search" class="sr-only">Search</label>
            <div class="relative w-full">
                <div
                    class="absolute inset-y-0 start-0 flex items-center justify-center w-14 pointer-events-none"
                >
                    <Icon
                        icon="material-symbols:link-rounded"
                        class="w-8 h-8 text-fuchsia-400"
                    />
                </div>
                <input
                    type="text"
                    id="simple-search"
                    bind:value={youtubeLinkOrQuery}
                    class="py-2.5 border border-gray-400 rounded ps-[3.5rem] text-heading text-sm focus:ring-fuchsia-400 focus:border-fuchsia-400 block w-full placeholder:text-body"
                    placeholder="Add Youtube Video URL or Search..."
                    required
                    disabled={!authToken}
                />

                <div
                    class="absolute z-10 w-full mt-2 bg-white rounded-xl shadow-xl overflow-hidden"
                >
                    {#if isSearching && !videoPreview && searchResults.length === 0}
                        <div
                            class="p-3 flex items-center justify-center text-gray-500 text-sm"
                        >
                            <Icon
                                icon="mdi:loading"
                                class="animate-spin w-5 h-5 mr-2"
                            />
                            Processing...
                        </div>
                    {/if}

                    {#if !analysisRunning && videoPreview && isUrl}
                        <div
                            class="flex flex-col p-3 space-y-1 bg-fuchsia-50 border-t-4 border-fuchsia-600"
                        >
                            <div class="flex gap-2">
                                <div class="img-wrapper">
                                    <img
                                        class="h-auto max-w-3xs rounded"
                                        src={videoPreview.thumbnail}
                                        alt="video thumbnail"
                                    />
                                </div>
                                <div class="preview-info">
                                    <h2 class="font-bold text-left text-xl">
                                        {videoPreview.title}
                                    </h2>

                                    <p
                                        class="font-sm font-light text-fuchsia-400"
                                    >
                                        {videoPreview.channelTitle}
                                    </p>

                                    <p
                                        class="text-sm text-gray-400 mb-2 line-clamp-3 overflow-hidden"
                                    >
                                        {videoPreview.description}
                                    </p>
                                </div>
                            </div>

                            <!-- svelte-ignore a11y_media_has_caption -->
                            <video
                                class="h-80 w-full self-center rounded-lg"
                                controls
                            >
                                <!-- NOTE: YouTube video URLs often can't be used directly in the <video> tag src attribute. You may need to replace this with an embedded iframe in a real production environment. -->
                                <source
                                    src={videoPreview.embedUrl}
                                    type="video/mp4"
                                />
                                Your browser does not support the video tag.
                            </video>
                        </div>
                    {/if}

                    {#if searchResults.length > 0 && !isUrl}
                        <!-- RENDER SEARCH RESULTS LIST -->
                        <ul
                            class="divide-y divide-gray-100 max-h-80 overflow-y-auto"
                        >
                            {#each searchResults as result}
                                <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
                                <li
                                    on:click={() => selectSearchResult(result)}
                                    on:keypress={() =>
                                        selectSearchResult(result)}
                                    class="flex items-center p-3 space-x-3 cursor-pointer hover:bg-gray-100 transition"
                                    role="button"
                                    tabindex="0"
                                >
                                    <img
                                        src={result.thumbnail}
                                        alt="Thumbnail"
                                        class="w-12 h-8 object-cover rounded"
                                    />
                                    <span
                                        class="text-sm text-gray-700 truncate flex-1"
                                        >{result.title}</span
                                    >
                                </li>
                            {/each}
                        </ul>
                    {/if}

                    {#if progress}
                        <div class="progress-wrapper p-2">
                            {#if progress !== "done"}
                                <div class="flex justify-start m-2">
                                    <span
                                        class="text-sm font-medium text-semibold capitalize"
                                        >{progress}...</span
                                    >
                                </div>
                                <div
                                    class="w-full bg-gray-200 rounded-full h-4"
                                >
                                    <div
                                        class="glass-progress-bar h-4 flex items-center justify-center rounded-full text-xs font-medium text-white text-center p-0.5 leading-none"
                                        style="width: {Math.max(
                                            progressPercentage(progress),
                                            8,
                                        )}%;"
                                    >
                                        {progressPercentage(progress)}%
                                        <span class="shine"></span>
                                    </div>
                                </div>
                            {/if}

                            {#if progress === "done"}
                                <p class="text-green-600 mt-2 font-semibold">
                                    Processing complete!
                                </p>
                            {/if}
                        </div>
                    {/if}
                </div>
            </div>

            <button
                on:click={startAnalysis}
                type="submit"
                class="inline-flex items-center justify-center shrink-0 text-white bg-fuchsia-400 hover:bg-fuchsia-500 focus:ring-4 focus:ring-fuchsia-300 shadow-xs rounded w-10 h-10 focus:outline-none cursor-pointer transition disabled:bg-gray-400"
                disabled={isSearching || analysisRunning || !authToken}
            >
                <Icon icon="material-symbols:search-rounded" class="w-6 h-6" />
            </button>
        </form>

        {#if analysisError}
            <div
                class="w-1/2 max-w-3xl mx-auto p-3 bg-red-100 border border-red-400 text-red-700 rounded-lg"
                role="alert"
            >
                <p class="font-bold">Analysis Failed</p>
                <p class="text-sm">{analysisError}</p>
                <p class="text-xs mt-1">
                    <span class="font-semibold">Debug Tip:</span> Check your FastAPI
                    console for the exact Supabase error message.
                </p>
            </div>
        {/if}
    {/if}
</div>

<style>
    .glass-progress-bar {
        position: relative;
        background: linear-gradient(90deg, #e879f9 80%, #e879f9 100%);
        overflow: hidden;
    }
    .glass-progress-bar .shine {
        position: absolute;
        top: 0;
        left: -100%;
        width: 50%;
        height: 100%;
        clip-path: polygon(20% 0, 100% 0, 80% 100%, 0% 100%);
        pointer-events: none;
        background: linear-gradient(
            90deg,
            rgba(255, 255, 255, 0.5) 0%,
            rgba(255, 255, 255, 0.45) 100%
        );
        animation: shine-move 1s infinite linear;
    }
    @keyframes shine-move {
        0% {
            left: -100%;
        }
        100% {
            left: 100%;
        }
    }
</style>
