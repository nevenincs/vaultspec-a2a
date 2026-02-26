/**
 * Compile-time exhaustiveness check for discriminated union switches.
 * Place in the `default` case of a switch statement.
 * TypeScript will error if any union member is unhandled.
 */
export function assertExhaustive(x: never): never {
  throw new Error(`Unhandled discriminated union member: ${JSON.stringify(x)}`);
}
