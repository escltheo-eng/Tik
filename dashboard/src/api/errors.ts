/**
 * Hiérarchie d'exceptions du dashboard, miroir de `sdk/exceptions.py`.
 *
 * Toutes les erreurs lancées par le client HTTP héritent de `TikError`,
 * pour pouvoir attraper « toute erreur Tik » d'un seul `catch` quand on
 * ne souhaite pas distinguer les cas.
 */

export class TikError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TikError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class AuthError extends TikError {
  constructor(message: string) {
    super(message);
    this.name = 'AuthError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class NotFoundError extends TikError {
  constructor(message: string) {
    super(message);
    this.name = 'NotFoundError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class ServerError extends TikError {
  constructor(message: string) {
    super(message);
    this.name = 'ServerError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class NetworkError extends TikError {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}
