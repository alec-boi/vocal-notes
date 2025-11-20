<script>
    import { supabase } from "../../lib/subabaseClient";
    import { onMount } from "svelte";
    import Icon from "@iconify/svelte";

    let message = "";

    async function signInWithGoogle() {
        const { error } = await supabase.auth.signInWithOAuth({
            provider: "google",
        });
        if (error) message = error.message;
    }

    onMount(async () => {
        const { data } = await supabase.auth.getSession();
        if (data.session) window.location.href = "/";
    });
</script>

<div class="w-full h-full relative">
    <div
        id="info-popup"
        tabindex="-1"
        class="overflow-y-auto overflow-x-hidden absolute inset-0 z-50 w-full h-full"
    >
        <div
            class="relative p-4 w-full h-full"
        >
            <div class="relative top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-2xl h-3/5 p-4 bg-white rounded-lg shadow">
                <div class="mb-4 text-2xl font-light text-gray-500">
                    <h3 class="mb-3 text-4xl font-bold text-gray-900">Login</h3>
                    <p>
                        Unfortunately, due to a lack of time and an internship that lead 
                        to what can only be called a "trammpoline suplexing" of a whole 
                        set of custom components, our website only supports login with Google.
                    </p>
                </div>
                <div
                    class="absolute left-0 right-0 bottom-0 flex justify-between items-center pt-0 p-4"
                >
                    <a
                        href="/"
                        class="font-medium text-xl text-fuchsia-300 hover:underline"
                        >Leave as a saveless wench</a
                    >
                    <div
                        class="items-center space-y-4"
                    >
                        <button
                            on:click={signInWithGoogle}
                            id="confirm-button"
                            type="button"
                            class="py-2 px-4 font-medium text-xl text-center text-white rounded-lg bg-fuchsia-400 hover:bg-fuchsia-400 focus:ring-4 focus:outline-none focus:ring-fuchsia-300 cursor-pointer"
                            >
                            Login with Google
                            
                            <Icon icon="flowbite:google-solid" class="inline" />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
