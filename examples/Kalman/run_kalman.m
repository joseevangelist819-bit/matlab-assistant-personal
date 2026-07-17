root=fileparts(mfilename('fullpath'));rng(20260714);N=300;A=[1 0.1;0 1];C=[1 0];Q=diag([1e-4 1e-3]);R=0.05;
x=zeros(2,N);z=zeros(1,N);for k=2:N,x(:,k)=A*x(:,k-1)+chol(Q,'lower')*randn(2,1);z(k)=C*x(:,k)+sqrt(R)*randn;end
xhat=zeros(2,N);P=eye(2);for k=2:N,xp=A*xhat(:,k-1);Pp=A*P*A'+Q;Kgain=Pp*C'/(C*Pp*C'+R);xhat(:,k)=xp+Kgain*(z(k)-C*xp);P=(eye(2)-Kgain*C)*Pp;end
measurement_rmse=sqrt(mean((z-x(1,:)).^2));estimate_rmse=sqrt(mean((xhat(1,:)-x(1,:)).^2));result=struct('measurement_rmse',measurement_rmse,'estimate_rmse',estimate_rmse,'improved',estimate_rmse<measurement_rmse);
save(fullfile(root,'result.mat'),'result','x','xhat','z');figure('Visible','off');plot(x(1,:));hold on;plot(z,':');plot(xhat(1,:));legend('true','measurement','estimate');grid on;exportgraphics(gcf,fullfile(root,'result.png'));close(gcf);
