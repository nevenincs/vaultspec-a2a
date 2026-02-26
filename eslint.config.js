import eslintPluginSvelte from 'eslint-plugin-svelte';
import tseslint from 'typescript-eslint';

export default [
  { ignores: ['node_modules/', '.svelte-kit/', 'build/', '.venv/', '.ruff_cache/'] },
  ...tseslint.configs.recommended,
  ...eslintPluginSvelte.configs['flat/recommended'],
];
