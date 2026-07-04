
import { PublicClientApplication, type AuthenticationResult } from '@azure/msal-browser';
import type { MSALConfig } from './AppConfig.js';

class MSAL {
    msalConfig: MSALConfig;
    publicClientApplication: PublicClientApplication;
    constructor(config: MSALConfig) {
        this.msalConfig = config;
        this.publicClientApplication = new PublicClientApplication(this.msalConfig);
    }


    public async authenticate(): Promise<AuthenticationResult> {
        const accessTokenRequest = {
            scopes: [`api://${this.msalConfig.auth.clientId}/${this.msalConfig.auth.scope}`]
        };
        return new Promise((resolve, reject) => {
            this.publicClientApplication.initialize().then(() => {
                this.publicClientApplication.handleRedirectPromise()
                    .then(redirectResponse => {
                        // Acquire token silent success
                        if (redirectResponse != null) {
                            this.publicClientApplication.setActiveAccount(redirectResponse.account);
                            resolve(redirectResponse);
                            //let account = publicClientApplication.getAllAccounts()[0];
                            // Call your API with token
                            //if (redirectResponse.expiresOn) {
                            //    let expireSeconds: number = (redirectResponse.expiresOn.getTime() - new Date().getTime()) / 1000;
                            //    if (redirectResponse.extExpiresOn != undefined) {
                            //        expireSeconds = (redirectResponse.extExpiresOn.getTime() - new Date().getTime()) / 1000;
                            //    }
                            //    if (expireSeconds <= 0) {
                            //        this.publicClientApplication.acquireTokenPopup(accessTokenRequest);
                            //    }
                            //}
                        }
                        else {
                            const account = this.publicClientApplication.getActiveAccount();
                            const silentRequest = {
                                ...accessTokenRequest,
                                account: account == null ? undefined : account
                            };
                            this.publicClientApplication.acquireTokenSilent(silentRequest)
                                .then(accessTokenResponse => {
                                    //console.log(`${new Date()} Acquire new token silent success.`)
                                    // Acquire token silent success
                                    resolve(accessTokenResponse);
                                    // Call your API with token
                                })
                                .catch(error => {
                                    this.publicClientApplication.acquireTokenRedirect(accessTokenRequest);
                                    reject(error);
                                });
                        }
                    })
            }).catch(err => reject(err));
        });
    }
}

export { MSAL, type AuthenticationResult };
