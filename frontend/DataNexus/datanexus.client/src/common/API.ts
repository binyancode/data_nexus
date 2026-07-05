import { MSAL, type AuthenticationResult } from './MSAL.js'
import { config } from './AppConfig.js'
import axios, { AxiosError } from 'axios'

interface IAPI {
    request: (api: string, method: string, body: any, needAuth: boolean) => Promise<any>,
    get: (api: string, needAuth: boolean) => Promise<any>,
    post: (api: string, body: any, needAuth: boolean) => Promise<any>,
    authenticate: () => Promise<AuthenticationResult>,
    on: (event: APIEvent) => EventPromise
}
enum APIEvent {
    Authenticate = "Authenticate",
    TokenExpired = "TokenExpired",
    Autherize = "Autherize",
    Request = "Request"
}

class EventPromise {
    private executor: (resolve: (value: any) => void, reject: (reason: any) => void) => void;
    private promise: Promise<any>;
    resolve: (value: any) => void = null as unknown as (value: any) => void;
    reject: (reason: any) => void = null as unknown as (value: any) => void;
    private _resolve: (value: any) => void = null as unknown as (value: any) => void;
    private _reject: (reason: any) => void = null as unknown as (value: any) => void;
    stopped: boolean = false;
    state: string = "pending";
    distinct: boolean = true;

    constructor() {
        this.executor = (resolve: (value: any) => void, reject: (reason: any) => void) => {
            this.resolve = resolve;
            this.reject = reject;
        };
        this.promise = new Promise<any>(this.executor);
    }

    then(resolve: (data: any) => void) {
        this._resolve = resolve;
        this.promise.then(
            (data) => {
                if (!this.distinct || ["pending", "rejected"].includes(this.state))
                    resolve(data);
                this.state = "resolved";
                if (this.stopped) return;
                this.promise = new Promise<any>(this.executor);
                this.then(this._resolve);
                this.catch(this._reject);
            });
        return this;
    }
    catch(reject: (reason: any) => void) {
        this._reject = reject;
        this.promise.catch(
            (reason) => {
                if (!this.distinct || ["pending", "resolved"].includes(this.state))
                    reject(reason);
                this.state = "rejected";
                if (this.stopped) return;
                this.promise = new Promise<any>(this.executor);
                this.then(this._resolve);
                this.catch(this._reject);
            });
        return this;
    }
    stop() {
        this.stopped = true;
    }
    all() {
        this.distinct = false;
    }
}

class API implements IAPI {
    static msal: Promise<MSAL> = null as unknown as Promise<MSAL>;
    static username: string = '';

    authenticated: boolean = false;
    autherized: boolean = false;

    constructor() {
        for (const key in APIEvent) {
            this.handlers[key] = new Array<EventPromise>();
        }
    }

    private handlers: Record<string, Array<EventPromise>> = {};

    public then(event: APIEvent, data: any): void {
        const handlers = this.handlers[event];
        if (!handlers) return;
        handlers.forEach(handler => {
            if (handler.stopped) {
                const index = handlers.indexOf(handler);
                if (index !== -1) {
                    handlers.splice(index, 1);
                }
                return;
            }
            handler.resolve(data);
        });
        //handlers.length = 0;
    }

    public catch(event: APIEvent, data: any): void {
        const handlers = this.handlers[event];
        if (!handlers) return;
        handlers.forEach(handler => {
            if (handler.stopped) {
                const index = handlers.indexOf(handler);
                if (index !== -1) {
                    handlers.splice(index, 1);
                }
                return;
            }
            handler.reject(data);
        });
        //handlers.length = 0;
    }

    on(event: APIEvent) {
        const promise = new EventPromise();
        if (!this.handlers[event]) {
            this.handlers[event] = [];
        }
        this.handlers[event]!.push(promise);
        return promise;
    }

    async request(api: string, method: string = "POST", data: any = {}, needAuth: boolean = true, unwrap: boolean = true, contentType = "application/json", silent: boolean = false, stream: boolean = false): Promise<any | AsyncIterable<string>> {
        const headers: Record<string, any> = {};

        if (needAuth) {
            const auth = await this.authenticate();
            const bearer = "Bearer " + auth.accessToken;
            headers.Authorization = bearer;
        }
        if (method != "GET") {
            headers["Content-Type"] = contentType;
        }

        if (stream) {
            const url = /^https?:\/\//.test(api) ? api : `api/${api}`;
            const response = await fetch(url, {
                method,
                headers,
                body: method !== "GET" ? JSON.stringify(data) : undefined,
            });

            if (!response.ok) {
                if (response.status === 401) {
                    this.autherized = false;
                    this.catch(APIEvent.Autherize, { api, err: new Error(`HTTP ${response.status}`) });
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            if (needAuth && !this.autherized) {
                this.autherized = true;
                this.then(APIEvent.Autherize, { api, response });
            }

            const reader = response.body!.getReader();
            const decoder = new TextDecoder();
            const self = this;

            return {
                [Symbol.asyncIterator]() {
                    return {
                        async next(): Promise<IteratorResult<string>> {
                            const { done, value } = await reader.read();
                            if (done) {
                                if (!silent) {
                                    self.then(APIEvent.Request, { api, response });
                                }
                                return { done: true, value: undefined };
                            }
                            return { done: false, value: decoder.decode(value, { stream: true }) };
                        },
                        async return(): Promise<IteratorResult<string>> {
                            reader.cancel();
                            return { done: true, value: undefined };
                        }
                    };
                }
            } as AsyncIterable<string>;
        }

        const config: Record<string, any> = {};
        if (method != "GET") {
            config.data = data;
        }
        config.url = /^https?:\/\//.test(api) ? api : `api/${api}`;
        config.method = method;
        config.headers = headers;
        config.responseType = "json";

        return new Promise((resolve, reject) => {
            axios(config)
                .then(response => {
                    if (needAuth) {
                        if (!this.autherized) {
                            this.autherized = true;
                            this.then(APIEvent.Autherize, { api, response });
                        }
                    }
                    if (response.status < 200 || response.status > 299) {
                        throw new AxiosError(`Response failed`, String(response.status), undefined, config, response);
                    }
                    if (response.data.state == "error") {
                        console.log(response.data);
                        throw new AxiosError(response.data.message, "400", undefined, config, response);
                    }
                    if (!silent) {
                        this.then(APIEvent.Request, { api, response });
                    }
                    return response;
                })
                .then(response => {
                    if (unwrap) {
                        resolve(response.data.data);
                    } else {
                        resolve(response.data);
                    }
                })
                .catch(err => {
                    if (err.response && err.response.status == 401) {
                        this.autherized = false;
                        this.catch(APIEvent.Autherize, { api, err });
                    }
                    else if (!silent) {
                        this.catch(APIEvent.Request, { api, err });
                    }
                    reject(err);
                });
        });
    }

    async get(api: string, needAuth: boolean = true, unwrap: boolean = true, contentType = "application/json", silent: boolean = false, stream: boolean = false): Promise<any> {
        return this.request(api, "GET", null, needAuth, unwrap, contentType, silent, stream);
    }

    async post(api: string, data: any, needAuth: boolean = true, unwrap: boolean = true, contentType = "application/json", silent: boolean = false, stream: boolean = false): Promise<any> {
        return this.request(api, "POST", data, needAuth, unwrap, contentType, silent, stream);
    }

    async del(api: string, needAuth: boolean = true, unwrap: boolean = true, contentType = "application/json", silent: boolean = false): Promise<any> {
        return this.request(api, "DELETE", null, needAuth, unwrap, contentType, silent);
    }

    async authenticate(refreshToken: boolean = false): Promise<AuthenticationResult> {
        if (API.msal == null) {
            // 优先从 BFF 取 config/MSAL（与 AIBI 一致）；BFF 未就绪时用本地 AppConfig 兜底
            API.msal = this.get('config/MSAL', false)
                .then(config => new MSAL(config))
                .catch(() => new MSAL(config.MSALConfig));
        }
        const msal = await API.msal;
        try {
            const auth: AuthenticationResult = await msal.authenticate();
            if (refreshToken){
                console.log(`${new Date()} Token refreshed:${auth.expiresOn}/${auth.extExpiresOn}.`)
            }
            if (!refreshToken && auth.expiresOn != null) {
                const expireSeconds: number = (auth.expiresOn.getTime() - new Date().getTime()) / 1000;
                if (expireSeconds <= 0) {
                    if (auth.extExpiresOn != undefined) {
                        const extExpireSeconds: number = (auth.extExpiresOn.getTime() - new Date().getTime()) / 1000;
                        if (expireSeconds <= 0 && extExpireSeconds > 0) {
                            console.log(`${new Date()} Token expired:${auth.expiresOn}/${auth.extExpiresOn}.`)
                            API.msal = null as unknown as Promise<MSAL>;
                            this.authenticated = false;
                            return await this.authenticate(true);
                        }
                        else if (extExpireSeconds <= 0) {
                            this.then(APIEvent.TokenExpired, auth);
                        }
                    }
                    else {
                        this.then(APIEvent.TokenExpired, auth);
                    }
                }
            }
            if (!this.authenticated) {
                this.authenticated = true;
                API.username = auth.account?.username || '';
                this.then(APIEvent.Authenticate, auth);
            }
            return auth;
        }
        catch (err) {
            this.authenticated = false;
            this.catch(APIEvent.Authenticate, err);
            throw err;
            //return null as unknown as AuthenticationResult;
        }
    }
}

export { API, APIEvent }
