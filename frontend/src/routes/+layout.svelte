<script>
  import "../app.css";
  import { supabase } from "$lib/subabaseClient";
  import Icon from "@iconify/svelte";
  import { onMount, onDestroy } from "svelte";
  import { sidebar as sidebarStore } from "$lib/sidebarStore";

  export let data;

  let user = null;

  let isMenuOpen = false;
  const toggleMenu = () => {
    isMenuOpen = !isMenuOpen;
  };

  $: {
    sidebarStore.set(data.sidebarComponent);
  }

  onMount(() => {
    const updateHeight = () => {
      const h = document.getElementById("main-header").offsetHeight;
      document.documentElement.style.setProperty("--header-height", `${h}px`);
    };

    updateHeight();
    window.addEventListener("resize", updateHeight);

    const { data: authListener } = supabase.auth.onAuthStateChange(
      (event, session) => {
        user = session?.user ?? null;
      },
    );

    return () => {
      window.removeEventListener("resize", updateHeight);
      authListener.subscription.unsubscribe();
    };
  });
</script>

<header id="main-header" class="fixed left-0 right-0 top-0 w-full">
  <nav class="bg-white w-full border-b-2 border-gray-200 pr-4 lg:pr-6 py-2.5">
    <div class="flex flex-wrap justify-between items-center">
      <div class="flex justify-center items-center gap-4">
        <button
          on:click={toggleMenu}
          type="button"
          class="inline-flex items-center p-2 ml-1 text-sm rounded-lg focus:outline-none"
          aria-controls="mobile-menu-2"
          aria-expanded={isMenuOpen}
        >
          <span class="sr-only">Open main menu</span>
          <svg
            class="w-8 h-8 fill-fuchsia-400 cursor-pointer"
            class:hidden={isMenuOpen}
            class:block={!isMenuOpen}
            viewBox="0 0 20 20"
            xmlns="http://www.w3.org/2000/svg"
            ><path
              fill-rule="evenodd"
              d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 15a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z"
              clip-rule="evenodd"
            ></path></svg
          >

          <svg
            class="w-8 h-8 fill-fuchsia-400 cursor-pointer"
            class:hidden={!isMenuOpen}
            class:block={isMenuOpen}
            viewBox="0 0 20 20"
            xmlns="http://www.w3.org/2000/svg"
            ><path
              fill-rule="evenodd"
              d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
              clip-rule="evenodd"
            ></path></svg
          >
        </button>

        <a href="/" class="flex items-center">
          <img src="/assets/logo.png" class="mr-3 h-[3rem]" alt="moo6-mascot" />
          <span
            class="self-center text-4xl font-semibold whitespace-nowrap text-fuchsia-400"
            >Moo6</span
          >
        </a>
      </div>

      <div class="flex items-center lg:order-2">
        {#if !user}
          <a
            href="/login"
            class="text-white bg-fuchsia-400 hover:bg-fuchsia-500 focus:ring-4 focus:ring-fuchsia-300 font-medium rounded-lg text-sm px-4 lg:px-5 py-2 lg:py-2.5 mr-2 focus:outline-none"
            >Log in</a
          >
          <a
            href="/dashboard"
            class="text-fuchsia-400 bg-white border-2 border-fuchsia-400 focus:ring-4 font-medium rounded-lg text-sm px-4 lg:px-5 py-2 lg:py-2.5 mr-2 focus:outline-none"
            >Get started</a
          >
        {:else}
          <span class="text-sm font-medium text-gray-700 mr-4">
            Welcome, {user.email ? user.email.split("@")[0] : "User"}!
          </span>
        {/if}
      </div>
    </div>
  </nav>
</header>

<aside
  id="default-sidebar"
  class="fixed left-0 z-40 w-64 transition-transform duration-300 {isMenuOpen
    ? 'translate-x-0'
    : '-translate-x-full'}"
  aria-label="Sidenav"
>
  <div
    class="overflow-y-auto absolute bottom-0 h-full w-full py-5 px-3 bg-white border-r-2 border-gray-200"
  >
    <ul class="pt-4 space-y-2">
      <li>
        <a
          href="/"
          class="flex items-center p-2 text-base font-normal text-gray-900 rounded-lg transition duration-75 hover:bg-fuchsia-400 hover:text-white group"
        >
          <Icon
            icon="material-symbols:ad-group-rounded"
            class="text-gray-400 w-8 h-8 group-hover:text-white"
          />
          <span class="ml-3 text-gray-400 group-hover:text-white"
            >Workspace</span
          >
        </a>
      </li>
      <li>
        <a
          href="/"
          class="flex items-center p-2 text-base font-normal text-gray-900 rounded-lg transition duration-75 hover:bg-fuchsia-400 group"
        >
          <Icon
            icon="material-symbols:music-note-add-rounded"
            class="text-gray-400 w-8 h-8 group-hover:text-white"
          />
          <span class="ml-3 text-gray-400 group-hover:text-white">Saved</span>
        </a>
      </li>
      <li>
        <a
          href="/"
          class="flex items-center p-2 text-base font-normal text-gray-900 rounded-lg transition duration-75 hover:bg-fuchsia-400 group"
        >
          <Icon
            icon="material-symbols:edit-note-rounded"
            class="text-gray-400 w-8 h-8 group-hover:text-white"
          />
          <span class="ml-3 text-gray-400 group-hover:text-white">Notice</span>
        </a>
      </li>
    </ul>
  </div>
  <div
    class="absolute bottom-0 left-0 justify-center p-4 w-full bg-white border-r-2 border-gray-200"
  >
    <a
      href="/logout"
      class="w-full py-2 flex items-center justify-center gap-2 text-gray-400 font-bold bg-inherit border-2 border-gray-300 rounded-lg cursor-pointer hover:border-fuchsia-400 group"
    >
      <Icon
        icon="mdi:logout"
        class="text-gray-400 w-6 h-6 group-hover:text-fuchsia-400"
      />
      <span class="group-hover:text-fuchsia-400">Sign Out</span>
    </a>
  </div>
</aside>

<div class="custom-sidebar-container flex flex-1 w-full min-h-screen">
  <aside class="w-64 min-h-screen border-r-2 border-gray-200 p-4 pt-20">
    {#if $sidebarStore}
      <svelte:component this={$sidebarStore} class="h-full" />
    {/if}
  </aside>

  <main class="w-full flex-1 p-6 mt-24">
    <slot />
  </main>
</div>

<style>
  :global(#default-sidebar) {
    top: var(--header-height);
    height: calc(100vh - var(--header-height));
  }

  #main-header {
    z-index: 99999999;
  }
</style>
