import eslintPluginSvelte from 'eslint-plugin-svelte';
import tseslint from 'typescript-eslint';

export default [
  {
    ignores: [
      'node_modules/',
      '.svelte-kit/',
      'build/',
      '.venv/',
      '.ruff_cache/',
      'src/ui/',
    ],
  },
  ...tseslint.configs.recommended,
  ...eslintPluginSvelte.configs['flat/recommended'],
];
