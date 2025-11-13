<script>
    import { supabase } from "../../lib/subabaseClient";
    import { onMount } from "svelte";

    let user = null;
    let data = "";
    let loading = true;

    onMount(async () => {
        const { data: sessionData } = await supabase.auth.getSession();
        const session = sessionData.session;
        user = session?.user;

        if (!user) {
            window.location.href = "/login";
            return;
        }

        const token = session.access_token;

        const res = await fetch(`${import.meta.env.VITE_API_URL}/protected`, {
            headers: { Authorization: `Bearer ${token}` },
        });

        const json = await res.json();
        data = json.message;
        loading = false;
    });

    async function logout() {
        await supabase.auth.signOut();
        window.location.href = "/login";
    }
</script>

<div class="p-6 text-center">
    
    <!-- <p>Hello, {user?.email}</p>
    <p class="mt-4 text-gray-600">{data}</p>
    <button
        on:click={logout}
        class="mt-6 bg-gray-800 text-white px-4 py-2 rounded"
    >
        Logout
    </button> -->
</div>
